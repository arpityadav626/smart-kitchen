# 🛡️ Smart Kitchen Safety & Automation System (SAFETY-FI 96X)

> **Axis Institute of Technology and Management (AITM)**  
> **Department of Computer Science & Engineering (AI & ML)**  
> **B.Tech CS-AIML Mini Project**  
> **Presented by:** Arpit Yadav (Lead Embedded Hardware & Systems Architect), Divyansh Jaiswal, and Abhay Upadhyay  
> **Guided by:** Ms. Shrestha Misra  
> **Core Philosophy:** *"Sense the hazard, decide at the controller, then alert and ventilate."*

---

## 📌 01. The Problem: Kitchen Hazards Need a Faster Response

Domestic kitchen hazards — combustible LPG leaks, cooking smoke, open flames, and thermal runaway — escalate exponentially when left unnoticed under manual supervision:

* **Manual Supervision:** A person must notice the hazardous condition first, introducing human delay, panic, and risk of asphyxiation or explosion.
* **Continuous Monitoring:** An array of embedded sensors continuously samples the atmosphere in real time with sub-second responsiveness.
* **Immediate Local Actuation:** Critical alarms and mechanical hazard mitigation (forced ventilation / sprinkler actuation) trigger autonomously at the controller level without cloud latency bottlenecks.

---

## ⚡ 02. System Architecture & Signal Pipeline

One unified system continuously monitors four core safety signals:

```
[INPUT SENSORS & 5V POWER BUS]
├── MQ-2 Sensor (Combustible Gas & Smoke • Analog Pin A0)
├── Optical IR Flame Sensor (Fire Detection • Active-LOW Pin 8)
├── DHT11 Climate Sensor (Ambient Temp °C & Humidity % • Pin 2)
└── 5V USB Power Bank Bus (Regulated Low-Voltage Distribution)
        │
        ▼ (Deterministic Microcontroller Ingestion)
[ARDUINO UNO ATmega328P LOGIC CONTROLLER]
├── Continuous Non-Blocking Multi-Hazard Evaluator
├── Safety Interlock Engine (Locks Exhaust Fan OFF during Fire)
└── 5-Second One-Shot Flame Sprinkler Timer
        │
        ▼ (Parallel Multi-Channel Output Actuation)
[LOCAL FEEDBACK & PHYSICAL ACTUATION]
├── 16×2 Character LCD Display (I2C Bus • SDA A4 / SCL A5)
├── Red Warning LED (Pin 5) & Safe Standby Green LED (Pin 3)
├── High-Decibel Acoustic Alert Buzzer (Pin 9)
├── 5V Isolated Relay Module (Inductive Back-EMF Suppressed)
├── 5V Mini DC Fume Extraction Exhaust Fan (Pin 7)
└── Submersible Water Pump Sprinkler Actuator (Pin 6)
        │
        ▼ (9600-Baud Serial Telemetry Bridge & WebSockets)
[THREE.JS 3D DIGITAL TWIN & WEB DASHBOARD]
├── Kinetic 3D Cooktop CAD Simulation & Dynamic Hazard Shaders
└── Cloud Smartphone Push Sentinel Alerts via Formspree Gateway
```

---

## 🔄 03. Response Logic & Cause → Effect Matrix

The system response is visible, audible, and automatic:

| Stage | Process | System Action |
| :--- | :--- | :--- |
| **1. Sensor Trigger** | Gas, smoke, flame, or heat changes raw input | Microcontroller ADC & digital registers capture transition |
| **2. Arduino Decision** | Real-time threshold evaluation in firmware | FSM transitions state without blocking delays |
| **3. LCD Message** | Immediate visual feedback | 16×2 I2C LCD displays status and climate metrics |
| **4. Warning Alert** | Multi-modal local alarm | Red warning LED and high-decibel acoustic buzzer activate |
| **5. Fan / Sprinkler Actuation** | Closed-loop hazard mitigation | 5V relay engages exhaust fan for gas/smoke; pump activates for flame |

---

## 🏠 04. Scaled 3D Physical Prototype (18 × 15")

The prototype looks like a real architectural kitchen rather than an exposed breadboard circuit:

* **18 × 15 Inch Open-Front Shell:** Features a detailed stove cooktop, chimney exhaust hood, sink, and refrigerator layout.
* **Visible Controls & Sensor Node:** MQ-2 sensor, optical flame sensor, and 16×2 character LCD are positioned in plain sight where hazard detection and visual feedback naturally occur.
* **Concealed 2.5-Inch Electronics Bay:** A 2.5-inch false floor conceals the Arduino Uno, relay module, breadboard power distribution, and harness wiring.

---

## 🔬 05. Safe 5V Demonstration Subsystems

All working elements run on an intrinsically safe, portable 5V low-voltage model system suitable for classrooms, auditoriums, and laboratory demonstrations without live hazard risks:

* **Control:** Arduino Uno (ATmega328P) and breadboard distribution module.
* **Sensing:** MQ-2 (gas & smoke), optical IR flame sensor, DHT11 (temp & humidity).
* **Feedback:** 16×2 character I2C LCD, acoustic buzzer, red & green status LEDs.
* **Action:** Active-LOW isolated 5V relay module, high-RPM mini DC exhaust fan, and submersible water pump sprinkler.
* **Power:** Portable 5V USB power bank bus with common ground reference.

---

## 🛠️ 06. 6-Stage Engineering Build Pipeline

1. **Source Components:** Acquired ATmega328P, MQ-2, optical flame sensor, DHT11, 16×2 I2C LCD, and 5V relays.
2. **Test Circuit on Breadboard:** Validated sensor thresholds and relay switching logic before mechanical integration.
3. **Upload Firmware:** Flashed deterministic non-blocking C++ embedded firmware (`smart_kitchen.ino`).
4. **Fabricate Shell:** Constructed the 18 × 15" open-front kitchen structure with custom cabinetry and appliances.
5. **Route Concealed Wiring:** Bundled and dressed all harness wiring within the 2.5" underfloor compartment.
6. **Validate States:** Conducted comprehensive smoke, gas, and flame simulation stress testing.

---

## 🚦 07. Tri-State Demonstration Machine

```
       ┌─────────────────────────────────────────────────────────┐
       │                 STATE 0: SAFE STANDBY                   │
       │  - Gas <= 600 ADC & Flame HIGH                          │
       │  - Green LED ON (Pin 3), Relays OFF (HIGH), Buzzer OFF  │
       │  - LCD: "T:27.5C H:52% / GAS:120 SAFE"                  │
       └──────────────┬───────────────────────────┬──────────────┘
                      │                           │
           Gas > 600  │                           │  Flame LOW
                      ▼                           ▼
┌───────────────────────────────────────┐   ┌────────────────────────────────────────┐
│     STATE 1: GAS LEAKAGE ALERT        │   │     STATE 2: FIRE EMERGENCY HAZARD     │
│ - Red / Blue LED ON                   │   │ - Red LED ON (Pin 5)                   │
│ - Exhaust Fan Relay ON (Pin 7 = LOW)  │   │ - Water Pump Relay ON (Pin 6 = LOW)    │
│ - Water Pump OFF (Pin 6 = HIGH)       │   │ - Exhaust Fan FORCED OFF (Pin 7 = HIGH)│
│ - Active Buzzer ON (Pin 9)            │   │ - Active Buzzer ON (Pin 9)             │
│ - LCD: "! GAS LEAKAGE ! / EXHAUST ON" │   │ - LCD: "! FIRE DETECTED ! / SPRINKLER" │
│ - Push Alerts: Dispatches phone alerts│   │ - Push Alerts: Dispatches phone alerts │
└───────────────────────────────────────┘   └────────────────────────────────────────┘
```

> **⚠️ Critical Safety Interlock:** During **State 2 (Fire Emergency)**, the Exhaust Fan is **strictly forced OFF** to avoid pulling fresh oxygen into the fire and feeding combustion.

---

## 📊 08. Empirical Validation & Testing Benchmark

| Test Area | Validation Method | Empirical Outcome |
| :--- | :--- | :--- |
| **Sensor Inputs** | Triggered simulated gas, smoke, flame, and climate shifts | Controller and alerts responded within **< 200ms** latency |
| **Gas Threshold** | Calibrated MQ-2 against indoor ambient baseline (350–400 ADC) | Trigger threshold set to **600 ADC counts**, eliminating false positives |
| **Relay & Noise Isolation** | Tested 1000µF decoupling capacitors across the 5V bus rail | **Zero back-EMF inductive resets** and zero PCF8574 I2C bus lockups |
| **LCD Integrity** | Monitored real-time status and hazard messages under continuous load | 100% readable feedback maintained across all operational transitions |
| **Continuous Operation** | Ran fully integrated setup on a 5V USB power bank | **60 minutes continuous** uninterrupted operational endurance |

---

## 🚀 09. Future Roadmap & Project Takeaways

* **Low-Cost Foundation:** Proven low-voltage 5V architecture for modular smart home safety integration.
* **Automatic Gas Regulator Shut-Off:** Mechanical servo-driven valve actuator to cut off LPG cylinders at the source.
* **Edge Vision Fire Detection:** On-device tinyML camera for spatial flame orientation and classification.
* **Cellular GSM (SIM800L) Fallback:** Direct SMS telephony dispatch during home broadband/WiFi power outages.
* **Ecosystem Integration:** Apple HomeKit, Matter, and Home Assistant smart-home bridge.

---

## 💻 Running the Live 3D Twin & Simulation Server

### Step 1: Start Server
```powershell
python app.py
```
*(or double-click `start_server.bat`)*

### Step 2: Open in Browser
👉 **[http://localhost:8000](http://localhost:8000)** or visit the live GitHub Pages preview at **[https://arpityadav626.github.io/smart-kitchen/](https://arpityadav626.github.io/smart-kitchen/)**.
