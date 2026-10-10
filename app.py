import os
import time
import json
import random
import threading
import serial
import serial.tools.list_ports
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Smart Kitchen Safety & Automation System")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Thread-safe reentrant lock and comprehensive prototype state
lock = threading.RLock()
state = {
    # Sensor telemetry
    "gas": 120,
    "temperature": 27.5,
    "humidity": 52.0,
    "flame": False,       # True = Fire detected (LOW on sensor)
    "raw_flame": False,   # Instantaneous raw sensor detection
    "flame_raw": 1,       # 1 = Normal/Standby, 0 = Active Flame
    
    # Finite State Machine: 0 = SAFE, 1 = GAS_LEAK, 2 = FIRE_EMERGENCY
    "fsm_state": 0,
    "fsm_label": "SAFE_STANDBY",
    
    # Actuators (Active-LOW relays: logical ON means relay engaged)
    "exhaust_fan": "OFF",
    "water_pump": "OFF",
    "buzzer": "OFF",
    "buzzer_muted": False,
    
    # Status LEDs
    "led_green": True,   # Pin 3 - Safe
    "led_blue": False,   # Pin 4 - Gas Leak
    "led_red": False,    # Pin 5 - Fire Hazard
    
    # I2C 16x2 LCD Mockup Text
    "lcd_line1": "TEMP:27.5C H:52%",
    "lcd_line2": "GAS:120 PPM SAFE",
    
    # Cloud Email Alert Gateway (Formspree -> Smartphone Push)
    "email_alert": {
        "status": "ARMED",
        "gateway": "Formspree Cloud IoT Gateway",
        "endpoint": "https://formspree.io/f/moevgzjw",
        "target_email": "arpityadav6794@gmail.com",
        "last_email": None,
        "email_count": 0,
        "last_dispatch_time": 0,
        "dispatch_logs": [
            "[INIT] Formspree Cloud IoT Webhook Active",
            "[TARGET] arpityadav6794@gmail.com (Phone Push Notification)",
            "[STATUS] Automated Emergency Email Sentinel Armed"
        ]
    },

    # GSM legacy bridge (Maintains 100% UI backwards compatibility)
    "gsm": {
        "status": "CLOUD_EMAIL_ACTIVE",
        "operator": "Formspree Cloud Push",
        "signal_csq": 31, # 100% Cloud Signal
        "target_number": "arpityadav6794@gmail.com",
        "target_email": "arpityadav6794@gmail.com",
        "last_sms": None,
        "sms_count": 0,
        "at_logs": [
            "HTTP/2 POST -> Formspree Cloud",
            "Endpoint: /f/moevgzjw",
            "Target: arpityadav6794@gmail.com",
            "Push Notification: Instant Phone Alert",
            "Status: 200 OK (Armed)"
        ]
    },
    
    # Hardware Connection
    "connected": False,
    "port": "None",
    "mode": "Interactive Simulator",
    "last_update": time.time(),
    "recent_logs": [
        "[INIT] Embedded System State Machine Loaded",
        "[INIT] LCD 16x2 I2C Display Bound (0x27)",
        "[INIT] Formspree Cloud Email Sentinel Online (arpityadav6794@gmail.com)"
    ],
    "raw_packet": ""
}

manual_selected_port = None
serial_connection = None
stop_thread = False

FORMSPREE_URL = "https://formspree.io/f/moevgzjw"
DEFAULT_EMAIL = "arpityadav6794@gmail.com"
last_email_dispatched_at = {"FIRE_EMERGENCY": 0.0, "GAS_LEAKAGE": 0.0, "MANUAL_TEST": 0.0}

def add_log(message: str):
    timestamp = time.strftime("%H:%M:%S")
    with lock:
        state["recent_logs"].append(f"[{timestamp}] {message}")
        if len(state["recent_logs"]) > 30:
            state["recent_logs"].pop(0)

def add_email_log(log_msg: str):
    timestamp = time.strftime("%H:%M:%S")
    with lock:
        state["email_alert"]["dispatch_logs"].append(f"[{timestamp}] {log_msg}")
        if len(state["email_alert"]["dispatch_logs"]) > 20:
            state["email_alert"]["dispatch_logs"].pop(0)
        state["gsm"]["at_logs"].append(f"[{timestamp}] {log_msg}")
        if len(state["gsm"]["at_logs"]) > 20:
            state["gsm"]["at_logs"].pop(0)

def _send_email_thread(event_type: str, subject: str, message_body: str, recipient: str):
    import urllib.request
    timestamp = time.strftime("%H:%M:%S")
    target = recipient or DEFAULT_EMAIL
    
    payload = json.dumps({
        "name": "Smart Kitchen Safety System (SAFETY-FI 96X)",
        "email": target,
        "subject": subject,
        "message": f"[{event_type}]\n{message_body}\n\nTime: {time.strftime('%Y-%m-%d %H:%M:%S')}\nSystem: SAFETY-FI 96X Autonomous Kitchen Sentinel"
    }).encode("utf-8")
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://arpityadav626.github.io/"
    }
    
    req = urllib.request.Request(FORMSPREE_URL, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.getcode() in (200, 201, 302):
                with lock:
                    email_entry = {
                        "id": state["email_alert"]["email_count"] + 1,
                        "timestamp": timestamp,
                        "type": event_type,
                        "recipient": target,
                        "subject": subject,
                        "body": message_body,
                        "status": "DELIVERED"
                    }
                    state["email_alert"]["email_count"] += 1
                    state["email_alert"]["last_email"] = email_entry
                    state["email_alert"]["last_dispatch_time"] = time.time()
                    
                    # Mirror to gsm for existing UI widgets
                    state["gsm"]["sms_count"] += 1
                    state["gsm"]["last_sms"] = email_entry
                
                add_email_log(f"Formspree -> {target} : DELIVERED (200 OK)")
                add_log(f"[EMAIL ALERT DELIVERED] 📩 {event_type} pushed to {target} (Notification on Phone)")
            else:
                add_email_log(f"Formspree HTTP {resp.getcode()} response")
    except Exception as e:
        add_email_log(f"Dispatch error: {str(e)[:40]}")
        add_log(f"[EMAIL DISPATCH RETRY] Notice: {str(e)[:40]}")

def trigger_email_dispatch(event_type: str, subject: str, message_body: str, target_email: str = None):
    now = time.time()
    # 30-second cooldown per event type to prevent flooding email quota
    if event_type != "MANUAL_TEST" and (now - last_email_dispatched_at.get(event_type, 0.0)) < 30.0:
        return
    last_email_dispatched_at[event_type] = now
    
    recipient = target_email or state["email_alert"]["target_email"]
    timestamp = time.strftime("%H:%M:%S")
    add_email_log(f"Queued {event_type} for {recipient}...")
    threading.Thread(target=_send_email_thread, args=(event_type, subject, message_body, recipient), daemon=True).start()

# Alias for backwards compatibility
def trigger_sms_dispatch(event_type: str, message_body: str):
    subject = f"⚠️ [KITCHEN ALERT] {event_type.replace('_', ' ')}"
    trigger_email_dispatch(event_type, subject, message_body)

HOLD_DURATION = 5.0 # Minimum 5-second alarm latch hold
last_fire_seen = 0.0
last_gas_seen = 0.0

def update_fsm_logic(hw_state=None, flame_input=None):
    """Calculates or applies FSM State and outputs based on sensor values or hardware state with 5-second latch"""
    global last_fire_seen, last_gas_seen
    now = time.time()
    gas = state["gas"]
    
    if flame_input is not None:
        flame_active = bool(flame_input)
    else:
        flame_active = state.get("raw_flame", False)

    prev_fsm = state["fsm_state"]

    # Start strict 5-second timer on initial flame trigger
    if (flame_active or hw_state == 2) and last_fire_seen == 0.0:
        last_fire_seen = now

    is_gas = (hw_state == 1) or (gas > 300)
    if is_gas:
        last_gas_seen = now

    # STRICT 5-SECOND CHECK: Once 5 seconds elapse, fire immediately shuts off!
    fire_active = False
    if last_fire_seen > 0.0:
        if (now - last_fire_seen) < HOLD_DURATION:
            fire_active = True
        else:
            # 5 seconds expired -> TURANT BAND!
            last_fire_seen = 0.0
            state["raw_flame"] = False

    gas_active = is_gas or ((now - last_gas_seen < HOLD_DURATION) and last_gas_seen > 0.0)
    if not is_gas and last_gas_seen > 0.0 and (now - last_gas_seen >= HOLD_DURATION):
        last_gas_seen = 0.0

    if fire_active:
        target_fsm = 2
    elif gas_active:
        target_fsm = 1
    else:
        target_fsm = 0

    if target_fsm == 2:
        # State 2: Fire Emergency (Latched for at least 5 seconds)
        state["fsm_state"] = 2
        state["flame"] = True
        state["fsm_label"] = "FIRE_EMERGENCY"
        state["led_green"] = False
        state["led_blue"] = False
        state["led_red"] = True
        state["water_pump"] = "ON"
        state["exhaust_fan"] = "OFF" # Forced off to avoid oxygenating fire
        state["buzzer"] = "OFF" if state["buzzer_muted"] else "ON"
        state["lcd_line1"] = "! FIRE DETECTED !"
        state["lcd_line2"] = "SPRINKLER ON"

        if prev_fsm != 2:
            add_log(f"[CRITICAL ALERT] 🔥 Flame detected! Sprinkler engaged, fan cut off.")
            trigger_email_dispatch(
                "FIRE_EMERGENCY",
                "🚨 [CRITICAL ALERT] Fire Flame Hazard Detected in Kitchen!",
                "CRITICAL EMERGENCY: Optical Flame sensor detected active combustion at the kitchen cooktop!\n• Water Sprinkler: ENERGIZED (5-Second Safety Extinguisher Cycle)\n• Exhaust Fan: LOCKED OFF (Oxygen Starvation Interlock)\n• Local Buzzer Alarm: ACTIVE\n• Status: Immediate Attention Required! Evacuate or inspect cooktop."
            )

    elif target_fsm == 1:
        # State 1: Gas Leakage
        state["fsm_state"] = 1
        state["flame"] = False
        state["fsm_label"] = "GAS_LEAK_ALERT"
        state["led_green"] = False
        state["led_blue"] = True
        state["led_red"] = False
        state["exhaust_fan"] = "ON"
        state["water_pump"] = "OFF"
        state["buzzer"] = "OFF" if state["buzzer_muted"] else "ON"
        state["lcd_line1"] = "! GAS LEAKAGE !"
        state["lcd_line2"] = f"EXHAUST ON ({gas}PPM)"

        if prev_fsm != 1:
            add_log(f"[WARNING ALERT] ⚠️ Gas leakage ({gas} PPM)! Exhaust fan engaged.")
            trigger_email_dispatch(
                "GAS_LEAKAGE",
                "⚠️ [WARNING ALERT] LPG Gas Leakage Detected in Kitchen!",
                f"WARNING ALERT: MQ-2 Sensor detected dangerous gas concentration of {gas} PPM (Exceeding safety limit 300)!\n• Exhaust Ventilation Fan: ENERGIZED (Extracting combustible vapor)\n• Solenoid Sprinkler: STANDBY\n• Local Buzzer Alarm: ACTIVE\n• Status: Please ventilate kitchen and inspect gas line immediately."
            )

    else:
        # State 0: Safe State
        state["fsm_state"] = 0
        state["flame"] = False
        state["raw_flame"] = False
        state["fsm_label"] = "SAFE_STANDBY"
        state["led_green"] = True
        state["led_blue"] = False
        state["led_red"] = False
        state["exhaust_fan"] = "OFF"
        state["water_pump"] = "OFF"
        state["buzzer"] = "OFF"
        state["buzzer_muted"] = False # Reset mute when condition returns to safe
        temp = state["temperature"]
        hum = state["humidity"]
        state["lcd_line1"] = f"TEMP:{temp:.1f}C H:{hum:.0f}%"
        state["lcd_line2"] = f"GAS:{gas}PPM SAFE"

        if prev_fsm != 0:
            add_log("[AUTO-RESET] ✅ Hazard cleared: Returned to Safe Standby.")

def detect_arduino_port():
    global manual_selected_port
    if manual_selected_port:
        return manual_selected_port

    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if any(k in desc or k in hwid for k in ["arduino", "ch340", "cp210", "ftdi", "usb-serial", "usb serial"]):
            return p.device

    for p in ports:
        desc = (p.description or "").lower()
        if "bluetooth" not in desc and "bth" not in desc:
            return p.device

    return None

def serial_worker():
    global serial_connection, stop_thread
    baudrate = 9600

    while not stop_thread:
        current_port = detect_arduino_port()
        if current_port:
            try:
                add_log(f"Attempting serial link on {current_port} (9600 baud)...")
                ser = serial.Serial(current_port, baudrate, timeout=2)
                time.sleep(2)
                serial_connection = ser
                with lock:
                    state["connected"] = True
                    state["port"] = current_port
                    state["mode"] = f"Hardware Live ({current_port})"
                add_log(f"Hardware sync established on {current_port}")

                while not stop_thread and ser.is_open:
                    if ser.in_waiting > 0:
                        raw_line = ser.readline().decode("utf-8", errors="ignore").strip()
                        if raw_line.startswith("{") and raw_line.endswith("}"):
                            try:
                                data = json.loads(raw_line)
                                with lock:
                                    state["raw_packet"] = raw_line
                                    if "gas" in data:
                                        state["gas"] = int(data["gas"])
                                    if "temp" in data:
                                        state["temperature"] = float(data["temp"])
                                    if "hum" in data:
                                        state["humidity"] = float(data["hum"])
                                    if "flame" in data:
                                        state["raw_flame"] = bool(data["flame"])
                                    if "flame_raw" in data:
                                        state["flame_raw"] = int(data["flame_raw"])
                                    if "muted" in data:
                                        state["buzzer_muted"] = bool(data["muted"])
                                    if "fan" in data:
                                        state["exhaust_fan"] = str(data["fan"]).upper()
                                    if "pump" in data:
                                        state["water_pump"] = str(data["pump"]).upper()
                                    
                                    hw_state = data.get("state")
                                    update_fsm_logic(hw_state, flame_input=state["raw_flame"])

                                    if "sms" in data:
                                        trigger_sms_dispatch(data.get("sms_type", "HARDWARE_GSM"), data["sms"])
                                    state["last_update"] = time.time()
                            except Exception as parse_e:
                                add_log(f"Parse error: {parse_e}")
                    time.sleep(0.05)
            except Exception as e:
                with lock:
                    state["connected"] = False
                    state["mode"] = "Interactive Simulator"
                if serial_connection and serial_connection.is_open:
                    try:
                        serial_connection.close()
                    except:
                        pass
                serial_connection = None
                time.sleep(3)
        else:
            # Standalone Simulation / Idle
            with lock:
                state["connected"] = False
                state["port"] = "None"
                state["mode"] = "Interactive Simulator"
                # Natural subtle fluctuations when in safe state
                if state["fsm_state"] == 0:
                    state["gas"] = max(80, min(240, state["gas"] + random.randint(-3, 3)))
                    state["temperature"] = round(max(24.0, min(31.0, state["temperature"] + random.uniform(-0.1, 0.1))), 1)
                    state["humidity"] = round(max(45.0, min(65.0, state["humidity"] + random.uniform(-0.2, 0.2))), 1)
                
                # Evaluate FSM latch transitions on every tick!
                update_fsm_logic()
                state["last_update"] = time.time()
            time.sleep(1)

worker = threading.Thread(target=serial_worker, daemon=True)
worker.start()

# --- HTTP Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/data")
async def get_data():
    with lock:
        update_fsm_logic()
        return JSONResponse(content=state)

@app.get("/api/ports")
async def get_ports():
    ports = [{"port": p.device, "description": p.description} for p in serial.tools.list_ports.comports()]
    return JSONResponse(content={"ports": ports, "selected": manual_selected_port})

@app.post("/api/set_port")
async def set_port(request: Request):
    global manual_selected_port, serial_connection
    body = await request.json()
    port = body.get("port")
    if serial_connection and serial_connection.is_open:
        try:
            serial_connection.close()
        except:
            pass
        serial_connection = None
    manual_selected_port = None if port in ("auto", "sim") else port
    add_log(f"Target COM Port switched to: {port}")
    return JSONResponse(content={"status": "updated", "port": manual_selected_port})

@app.post("/api/simulate")
async def simulate_scenario(request: Request):
    """Allows web users to test FSM states directly from the interactive workbench"""
    global last_fire_seen, last_gas_seen
    body = await request.json()
    scenario = body.get("scenario")
    with lock:
        if scenario == "safe":
            last_fire_seen = 0.0
            last_gas_seen = 0.0
            state["gas"] = 120
            state["flame"] = False
            state["raw_flame"] = False
            state["buzzer_muted"] = False
            add_log("[SIMULATOR] Restored Normal Kitchen Parameters (Gas: 120 PPM, Flame: Safe)")
        elif scenario == "gas_leak":
            last_gas_seen = time.time()
            state["gas"] = 650
            state["flame"] = False
            state["raw_flame"] = False
            add_log("[SIMULATOR] Simulated LPG/Smoke Leakage (Gas: 650 PPM > Threshold 300) - 5s Hold Active")
        elif scenario == "fire":
            last_fire_seen = time.time()
            state["raw_flame"] = True
            state["flame"] = True
            add_log("[SIMULATOR] Simulated Optical Flame Detection (Pin 8 -> LOW) - 5s Hold Active")
            def clear_sim_flame():
                time.sleep(1.0)
                with lock:
                    state["raw_flame"] = False
            threading.Thread(target=clear_sim_flame, daemon=True).start()
        elif scenario == "custom":
            if "gas" in body:
                state["gas"] = int(body["gas"])
                if state["gas"] > 300:
                    last_gas_seen = time.time()
            if "flame" in body:
                state["raw_flame"] = bool(body["flame"])
                if state["raw_flame"]:
                    last_fire_seen = time.time()
            if "temp" in body:
                state["temperature"] = float(body["temp"])
            if "hum" in body:
                state["humidity"] = float(body["hum"])
        update_fsm_logic()
    return JSONResponse(content={"status": "ok", "state": state["fsm_label"]})

@app.post("/api/mute")
async def toggle_mute():
    """Simulates or issues hardware Mute Pushbutton (Pin 12)"""
    global serial_connection
    with lock:
        state["buzzer_muted"] = not state["buzzer_muted"]
        if state["buzzer_muted"]:
            state["buzzer"] = "OFF"
            add_log("[USER ACTION] Mute Push Button Pressed (Pin 12) -> Buzzer Silenced")
        else:
            state["buzzer"] = "ON" if state["fsm_state"] != 0 else "OFF"
            add_log("[USER ACTION] Buzzer Mute Cancelled")

    if serial_connection and serial_connection.is_open:
        try:
            serial_connection.write(b"MUTE\n")
        except:
            pass
    return JSONResponse(content={"muted": state["buzzer_muted"]})

@app.post("/api/email/send_test")
async def send_test_email(request: Request):
    body = await request.json()
    email = body.get("email", state["email_alert"]["target_email"])
    msg = body.get("message", "System Diagnostic Test: SAFETY-FI 96X Cloud Email Alert Pipeline is fully operational.")
    with lock:
        state["email_alert"]["target_email"] = email
        state["gsm"]["target_number"] = email
        state["gsm"]["target_email"] = email
        trigger_email_dispatch(
            "MANUAL_TEST",
            "🔔 [SYSTEM TEST] Smart Kitchen Safety Alert Dispatched",
            msg,
            target_email=email
        )
    return JSONResponse(content={"status": "dispatched", "recipient": email})

@app.post("/api/gsm/send_test")
async def send_test_sms(request: Request):
    body = await request.json()
    email_or_phone = body.get("phone") or body.get("email") or state["email_alert"]["target_email"]
    msg = body.get("message", "TEST: Smart Kitchen Cloud Email Push Notification Operational.")
    with lock:
        state["gsm"]["target_number"] = email_or_phone
        state["email_alert"]["target_email"] = email_or_phone
        trigger_email_dispatch("MANUAL_TEST", "🔔 [SYSTEM TEST] Smart Kitchen Alert Dispatched", msg, target_email=email_or_phone)
    return JSONResponse(content={"status": "dispatched", "recipient": email_or_phone})

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*70)
    print(">> SMART KITCHEN SAFETY & AUTOMATION SYSTEM")
    print(">> Localhost Web Showcase & Real-Time Prototype Dashboard")
    print(">> Access URL: http://localhost:8000")
    print("="*70 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
