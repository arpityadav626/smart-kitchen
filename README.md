# 🛡️ Smart Kitchen Safety & Automation System (Embedded IoT Engineering Prototype)

An industrial-grade embedded engineering prototype and interactive web showcase built for the **Arduino Uno (ATmega328P)**. Features deterministic multi-sensor hazard mitigation, a **Finite State Machine (FSM)**, **I2C 16x2 Character LCD Telemetry**, **SIM800L Cellular GSM Emergency SMS Dispatch**, and **Industrial Noise & Power Isolation**.

---

## ⚡ Core Technical Specifications

### 1. Hardware Pinout & Wiring Matrix

| Component | Arduino Uno Pin | Signal Type | Logic Level / Threshold | Function |
| :--- | :--- | :--- | :--- | :--- |
| **MQ Gas / Smoke Sensor** | **Analog Pin `A0`** | Analog Input (0-5V) | `> 400` ADC (PPM) | Continuous LPG, methane & combustion smoke sensing |
| **Optical Flame Sensor** | **Digital Pin `8`** | Digital Input | **Active LOW** (`LOW` = Flame) | Optical infrared flame radiation detection |
| **DHT11 Climate Sensor** | **Digital Pin `2`** | 1-Wire Digital | Serial Bitstream | Ambient temperature (°C) & relative humidity (%) |
| **Exhaust Fan Relay** | **Digital Pin `7`** | Digital Output | **Active-LOW** (`LOW` = ON) | High-RPM smoke/gas extraction fan |
| **Water Pump Sprinkler Relay** | **Digital Pin `6`** | Digital Output | **Active-LOW** (`LOW` = ON) | Extinguishes fire hazards via water spray |
| **Active Buzzer** | **Digital Pin `9`** | Digital Output | `HIGH` = Alarm Sound | High-decibel acoustic alert |
| **Mute Tactile Pushbutton**| **Digital Pin `12`** | Digital Input | `INPUT_PULLUP` (`LOW` = Pressed)| Instantly silences buzzer without cutting relays |
| **Safe Status LED (Green)**| **Digital Pin `3`** | Digital Output | `HIGH` = ON (220Ω resistor) | Indicates normal operational standby |
| **Gas Leak Status LED (Blue)**| **Digital Pin `4`** | Digital Output | `HIGH` = ON (220Ω resistor) | Indicates toxic gas / LPG concentration |
| **Fire Hazard LED (Red)**  | **Digital Pin `5`** | Digital Output | `HIGH` = ON (220Ω resistor) | Indicates active combustion fire hazard |
| **16x2 Character LCD**     | **`A4` (SDA), `A5` (SCL)** | I2C Bus Protocol | 100 kHz (Address `0x27`) | Real-time environment metrics & alert messages |
| **SIM800L GSM Module**     | **Pin `10` (RX), `11` (TX)**| SoftwareSerial UART | 9600 Baud AT Commands | Dispatches emergency SMS to phone upon alarms |

---

## 🔄 Finite State Machine (FSM) Decision Engine

```
       ┌─────────────────────────────────────────────────────────┐
       │                 STATE 0: SAFE STANDBY                   │
       │  - Gas <= 400 & Flame HIGH                              │
       │  - Green LED ON (Pin 3), Relays OFF (HIGH), Buzzer OFF  │
       │  - LCD: "T:27.5C H:52% / GAS:120 SAFE"                  │
       └──────────────┬───────────────────────────┬──────────────┘
                      │                           │
           Gas > 400  │                           │  Flame LOW
                      ▼                           ▼
┌───────────────────────────────────────┐   ┌────────────────────────────────────────┐
│     STATE 1: GAS LEAKAGE ALERT        │   │     STATE 2: FIRE EMERGENCY HAZARD     │
│ - Blue LED ON (Pin 4)                 │   │ - Red LED ON (Pin 5)                   │
│ - Exhaust Fan Relay ON (Pin 7 = LOW)  │   │ - Water Pump Relay ON (Pin 6 = LOW)    │
│ - Water Pump OFF (Pin 6 = HIGH)       │   │ - Exhaust Fan FORCED OFF (Pin 7 = HIGH)│
│ - Active Buzzer ON (Pin 9)            │   │ - Active Buzzer ON (Pin 9)             │
│ - LCD: "! GAS LEAKAGE ! / EXHAUST ON" │   │ - LCD: "! FIRE DETECTED ! / SPRINKLER" │
│ - GSM: Dispatches Gas SMS via SIM800L │   │ - GSM: Dispatches Fire SMS via SIM800L │
└───────────────────────────────────────┘   └────────────────────────────────────────┘
```

> **⚠️ Critical Safety Interlock:** During **State 2 (Fire Emergency)**, the Exhaust Fan is **strictly forced OFF** to avoid pulling fresh oxygen into the fire and feeding combustion.

---

## 📱 Cellular GSM (SIM800L) Telemetry & AT Commands

When a state transition from `SAFE` to `GAS_LEAK` or `FIRE_EMERGENCY` occurs, the firmware issues standard GSM Hayes AT commands:

```text
AT+CMGF=1                                   -> Sets SMS Text Mode
AT+CMGS="+919876543210"                     -> Target Emergency Phone Number
> ALERT: LPG Gas Leakage detected (>400 PPM)! Exhaust fan engaged.
^Z (ASCII 0x1A)                             -> Submits SMS dispatch packet
```

---

## 🔌 Power Delivery & Noise Isolation Engineering

1. **DC-DC Step-Down Buck Converter (12V in to regulated 5.0V, 3A capacity):**
   - The Arduino Uno onboard linear voltage regulator (AMS1117) overheats and trips when supplying >500mA.
   - The **SIM800L module draws up to 2.0A peak burst currents** during GSM network transmission, and dual relays draw ~140mA. A dedicated 3A Buck Converter with common ground ensures zero brownout resets.

2. **1000µF 25V Decoupling Electrolytic Capacitors:**
   - Placed directly across the 5.0V and GND rail terminals.
   - **Suppresses Relay Back-EMF:** When mechanical relay coils de-energize, inductive voltage spikes kick back onto the 5V bus. Without this capacitor, inductive spikes cause the PCF8574 I2C bus to crash, permanently freezing the 16x2 LCD display.

---

## 💻 Running the Web Showcase & Live Simulator

### Step 1: Start Server
```powershell
python app.py
```
*(or double-click `start_server.bat`)*

### Step 2: Open in Browser
👉 **[http://localhost:8000](http://localhost:8000)**

- **Interactive Workbench:** Click **"Safe Standby"**, **"Trigger Gas Leak"**, or **"Trigger Fire Hazard"** to watch the virtual 16x2 LCD, LEDs, Relays, and GSM SMS feed react in real time.
- **Physical Arduino Mode:** Plug your Arduino Uno via USB. The backend will auto-detect the COM port and mirror live hardware sensor telemetry.
