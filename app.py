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
    
    # GSM / SIM800L Module Telemetry
    "gsm": {
        "status": "READY",
        "operator": "Airtel 4G/2G",
        "signal_csq": 26, # 0 to 31
        "target_number": "+91 98765 43210",
        "last_sms": None,
        "sms_count": 0,
        "at_logs": [
            "AT -> OK",
            "AT+CPIN? -> +CPIN: READY",
            "AT+CREG? -> +CREG: 0,1 (Home Network)",
            "AT+CSQ -> +CSQ: 26,0",
            "AT+CMGF=1 -> OK (Text Mode Ready)"
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
        "[INIT] SIM800L GSM Telemetry Subsystem Online"
    ],
    "raw_packet": ""
}

manual_selected_port = None
serial_connection = None
stop_thread = False

def add_log(message: str):
    timestamp = time.strftime("%H:%M:%S")
    with lock:
        state["recent_logs"].append(f"[{timestamp}] {message}")
        if len(state["recent_logs"]) > 30:
            state["recent_logs"].pop(0)

def add_gsm_log(at_command: str):
    timestamp = time.strftime("%H:%M:%S")
    with lock:
        state["gsm"]["at_logs"].append(f"[{timestamp}] {at_command}")
        if len(state["gsm"]["at_logs"]) > 20:
            state["gsm"]["at_logs"].pop(0)

def trigger_sms_dispatch(event_type: str, message_body: str):
    timestamp = time.strftime("%H:%M:%S")
    with lock:
        sms_entry = {
            "id": state["gsm"]["sms_count"] + 1,
            "timestamp": timestamp,
            "type": event_type,
            "recipient": state["gsm"]["target_number"],
            "body": message_body,
            "status": "DELIVERED"
        }
        state["gsm"]["sms_count"] += 1
        state["gsm"]["last_sms"] = sms_entry
        state["gsm"]["at_logs"].append(f'[{timestamp}] AT+CMGS="{state["gsm"]["target_number"]}"')
        state["gsm"]["at_logs"].append(f'[{timestamp}] > {message_body}')
        state["gsm"]["at_logs"].append(f"[{timestamp}] +CMGS: 42 -> SMS SENT OK")
        if len(state["gsm"]["at_logs"]) > 20:
            state["gsm"]["at_logs"].pop(0)
        state["recent_logs"].append(f"[{timestamp}] [GSM ALERT DISPATCHED] {event_type} to {state['gsm']['target_number']}")
        if len(state["recent_logs"]) > 30:
            state["recent_logs"].pop(0)

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

    is_gas = (hw_state == 1) or (gas > 400)
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
            trigger_sms_dispatch(
                "FIRE_EMERGENCY",
                "CRITICAL: Fire flame hazard detected in Kitchen! Sprinkler engaged, fan cut off. Evacuate!"
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
            trigger_sms_dispatch(
                "GAS_LEAKAGE",
                f"WARNING: LPG Gas concentration {gas} PPM (threshold 400). Exhaust fan active. Ventilate immediately!"
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
            add_log("[SIMULATOR] Simulated LPG/Smoke Leakage (Gas: 650 PPM > Threshold 400) - 5s Hold Active")
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
                if state["gas"] > 400:
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

@app.post("/api/gsm/send_test")
async def send_test_sms(request: Request):
    body = await request.json()
    msg = body.get("message", "TEST: Smart Kitchen Telemetry System Operational.")
    phone = body.get("phone", state["gsm"]["target_number"])
    with lock:
        state["gsm"]["target_number"] = phone
        trigger_sms_dispatch("MANUAL_TEST", msg)
    return JSONResponse(content={"status": "dispatched", "recipient": phone})

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*70)
    print(">> SMART KITCHEN SAFETY & AUTOMATION SYSTEM")
    print(">> Localhost Web Showcase & Real-Time Prototype Dashboard")
    print(">> Access URL: http://localhost:8000")
    print("="*70 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
