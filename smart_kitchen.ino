/*
 * ====================================================================================================
 * PROJECT: Smart Kitchen Safety & Autonomous Hazard Mitigation System
 * TARGET PLATFORM: Arduino Uno (Microchip ATmega328P @ 16 MHz)
 * ARCHITECTURE: Finite State Machine (FSM) + Non-Blocking millis() Scheduling
 * AUTHOR: Principal Embedded Systems Architect
 * ====================================================================================================
 *
 * HARDWARE INTERFACE & PIN ASSIGNMENTS:
 * ----------------------------------------------------------------------------------------------------
 * 1. SENSORS:
 *    - MQ Gas / Smoke Sensor           -> Analog Pin A0 (ADC 0-1023, Gas Threshold: >400)
 *    - Optical Flame Sensor (IR)       -> Digital Pin 8 (Active-LOW TTL: LOW = Combustion IR Detected)
 *    - DHT11 Environmental Sensor      -> Digital Pin 2 (1-Wire Proprietary Serial Stream)
 *    - Tactile Alarm Mute Pushbutton   -> Digital Pin 12 (INPUT_PULLUP: LOW = Actuated)
 *
 * 2. ACTUATORS & ALARMS:
 *    - Status LED Green (Safe Standby) -> Digital Pin 3 (Active-HIGH via 220 Ohm Resistor)
 *    - Status LED Blue (Gas Leak)      -> Digital Pin 4 (Active-HIGH via 220 Ohm Resistor)
 *    - Status LED Red (Fire Hazard)    -> Digital Pin 5 (Active-HIGH via 220 Ohm Resistor)
 *    - Active Piezo Buzzer             -> Digital Pin 9 (Active-HIGH Driver)
 *    - Exhaust Fan Relay Module        -> Digital Pin 7 (Active-LOW Opto-Isolated Relay Coil)
 *    - Water Sprinkler Pump Relay      -> Digital Pin 6 (Active-LOW Opto-Isolated Relay Coil)
 *
 * 3. COMMUNICATION BUSES:
 *    - I2C Bus (PCF8574 Backpack)      -> SDA (Pin A4), SCL (Pin A5) [Address: 0x27 or 0x3F, 100 kHz]
 *    - SIM800L GSM Cellular Modem      -> SoftwareSerial UART (Baud: 9600 bps)
 *                                         Arduino Pin 10 (RX) <- SIM800L TXD (Direct TTL)
 *                                         Arduino Pin 11 (TX) -> SIM800L RXD (via 1k/2k Voltage Divider to 3.3V)
 *
 * 4. POWER & NOISE ISOLATION ARCHITECTURE:
 *    - LM2596 High-Efficiency Buck Converter: Steps 12V DC input down to regulated 5.0V logic rail
 *      and dedicated 4.0V rail for SIM800L capable of 2.0A peak burst transmission pulses.
 *    - 1000uF 25V Low-ESR Decoupling Electrolytic Capacitors installed in parallel across VCC/GND
 *      terminals to absorb inductive back-EMF from mechanical relay coils and pump motor start-up transients.
 *    - Periodic 10-Second I2C Bus Recovery Routine (bootLcdScreen) implemented to prevent PCF8574 register lockups.
 * ====================================================================================================
 */

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <SoftwareSerial.h>

// --- HARDWARE PIN DEFINITIONS ---
#define PIN_MQ_GAS         A0
#define PIN_FLAME          8
#define PIN_DHT            2
#define PIN_BUZZER         9
#define PIN_RELAY_FAN      7     // Active-LOW: LOW = Relay Energized, HIGH = Relay Cut Off
#define PIN_RELAY_PUMP     6     // Active-LOW: LOW = Relay Energized, HIGH = Relay Cut Off
#define PIN_LED_GREEN      3
#define PIN_LED_BLUE       4
#define PIN_LED_RED        5
#define PIN_BTN_MUTE       12    // Internal Pull-Up Enabled

#define PIN_GSM_RX         10    // Arduino RX <- SIM800L TX
#define PIN_GSM_TX         11    // Arduino TX -> SIM800L RX (via Voltage Divider)

// --- SYSTEM CONSTANTS & CALIBRATION ---
#define DHTTYPE            DHT11
#define GAS_THRESHOLD      400   // Raw ADC units (Safe <= 400, Hazard > 400)
#define RELAY_ACTIVE       LOW   // Active-LOW optocoupler trigger
#define RELAY_INACTIVE     HIGH  // Coil de-energized

// Emergency Dispatch Phone Number
const char EMERGENCY_PHONE[] = "+919876543210";

// --- FINITE STATE MACHINE (FSM) ENUMERATION ---
enum SystemState {
  STATE_SAFE = 0,
  STATE_GAS_LEAK = 1,
  STATE_FIRE_EMERGENCY = 2
};

SystemState currentState = STATE_SAFE;
SystemState previousState = STATE_SAFE;

// --- HARDWARE DRIVER INSTANCES ---
DHT dht(PIN_DHT, DHTTYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2); // Default PCF8574 address
SoftwareSerial gsmSerial(PIN_GSM_RX, PIN_GSM_TX);

// --- TELEMETRY & CONTROL FLAGS ---
bool buzzerMuted = false;
bool lastBtnState = HIGH;
unsigned long lastDebounceTime = 0;
const unsigned long debounceDelay = 50;

// Non-blocking Millis Timers
unsigned long lastSensorReadTime = 0;
const unsigned long sensorInterval = 1000;   // 1 Hz telemetry cycle

unsigned long lastLcdRecoveryTime = 0;
const unsigned long lcdRecoveryInterval = 10000; // 10-Second I2C Noise Recovery Routine

// --- FUNCTION PROTOTYPES ---
void bootLcdScreen();
void initGsmModem();
void sendEmergencySms(const char* message);
void executeFsmLogic(int gasVal, bool flameDetected, float temp, float hum);
void refreshLcdBuffer(const char* line1, const char* line2);
void pollMutePushbutton();
void transmitTelemetry(int gasVal, bool flameDetected, float temp, float hum);

void setup() {
  // 1. Initialize Hardware Serial for USB Web-Serial & Telemetry Link
  Serial.begin(9600);

  // 2. Initialize SoftwareSerial for Cellular GSM Modem
  gsmSerial.begin(9600);

  // 3. Configure Input Pins
  pinMode(PIN_MQ_GAS, INPUT);
  pinMode(PIN_FLAME, INPUT);
  pinMode(PIN_BTN_MUTE, INPUT_PULLUP);

  // 4. Configure Output Pins & Establish Fail-Safe State
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_RELAY_FAN, OUTPUT);
  pinMode(PIN_RELAY_PUMP, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_BLUE, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);

  // Set relays to de-energized (Active-LOW: HIGH is OFF)
  digitalWrite(PIN_RELAY_FAN, RELAY_INACTIVE);
  digitalWrite(PIN_RELAY_PUMP, RELAY_INACTIVE);
  digitalWrite(PIN_BUZZER, LOW);
  
  // Power indicator LED: Safe Standby
  digitalWrite(PIN_LED_GREEN, HIGH);
  digitalWrite(PIN_LED_BLUE, LOW);
  digitalWrite(PIN_LED_RED, LOW);

  // 5. Initialize DHT Climate Sensor
  dht.begin();

  // 6. Execute LCD Hardware Boot & Recovery Sequence
  bootLcdScreen();
  refreshLcdBuffer("SMART KITCHEN", "SYSTEM BOOTING");

  // 7. Initialize SIM800L Cellular Modem
  initGsmModem();

  refreshLcdBuffer("SYSTEM ONLINE", "FSM SUPERVISED");
  delay(1200);
}

void loop() {
  // 1. Non-Blocking Tactile Mute Button Polling (Debounced)
  pollMutePushbutton();

  // 2. Process Bidirectional Commands from Web Dashboard (e.g., MUTE override)
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command == "MUTE") {
      buzzerMuted = !buzzerMuted;
      if (buzzerMuted) digitalWrite(PIN_BUZZER, LOW);
    }
  }

  unsigned long currentMillis = millis();

  // 3. Periodic 10-Second I2C Noise Recovery Sequence (Prevents PCF8574 Lockup)
  if (currentMillis - lastLcdRecoveryTime >= lcdRecoveryInterval) {
    lastLcdRecoveryTime = currentMillis;
    if (currentState == STATE_SAFE) {
      bootLcdScreen();
    }
  }

  // 4. Primary 1 Hz Telemetry & FSM Evaluation Loop
  if (currentMillis - lastSensorReadTime >= sensorInterval) {
    lastSensorReadTime = currentMillis;

    // Read Hardware Sensor Signals
    int gasVal = analogRead(PIN_MQ_GAS);
    int flameRaw = digitalRead(PIN_FLAME);
    bool flameDetected = (flameRaw == LOW); // Optical sensor triggers LOW on combustion IR

    float temp = dht.readTemperature();
    float hum = dht.readHumidity();

    // Fallback values if 1-Wire check fails
    if (isnan(temp)) temp = 27.0;
    if (isnan(hum)) hum = 48.0;

    // Execute Deterministic FSM State Transitions
    executeFsmLogic(gasVal, flameDetected, temp, hum);

    // Stream Structured Telemetry to USB Serial (Universal Comma-Delimited & JSON)
    transmitTelemetry(gasVal, flameDetected, temp, hum);
  }
}

/*
 * ====================================================================================================
 * FINITE STATE MACHINE (FSM) DECISION LOGIC
 * ====================================================================================================
 */
void executeFsmLogic(int gasVal, bool flameDetected, float temp, float hum) {
  // Determine Next State based on Hazard Priority Hierarchy (Fire > Gas > Safe)
  if (flameDetected) {
    currentState = STATE_FIRE_EMERGENCY;
  } else if (gasVal > GAS_THRESHOLD) {
    currentState = STATE_GAS_LEAK;
  } else {
    currentState = STATE_SAFE;
    buzzerMuted = false; // Reset mute latch upon returning to safe environment
  }

  // Execute State-Specific Actuation
  switch (currentState) {
    case STATE_SAFE:
      // Status LEDs: Green ON, Blue/Red OFF
      digitalWrite(PIN_LED_GREEN, HIGH);
      digitalWrite(PIN_LED_BLUE, LOW);
      digitalWrite(PIN_LED_RED, LOW);

      // Actuators: Relays De-energized (HIGH), Buzzer Silent
      digitalWrite(PIN_RELAY_FAN, RELAY_INACTIVE);
      digitalWrite(PIN_RELAY_PUMP, RELAY_INACTIVE);
      digitalWrite(PIN_BUZZER, LOW);

      // LCD Display: Live Climate & Gas Telemetry
      char l1[17];
      char l2[17];
      snprintf(l1, sizeof(l1), "T:%.0fC  H:%.0f%%", temp, hum);
      snprintf(l2, sizeof(l2), "Gas:%d [Safe]", gasVal);
      refreshLcdBuffer(l1, l2);
      break;

    case STATE_GAS_LEAK:
      // Status LEDs: Blue ON, Green/Red OFF
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_BLUE, HIGH);
      digitalWrite(PIN_LED_RED, LOW);

      // Actuators: Exhaust Fan Active (LOW), Pump Off, Buzzer Active
      digitalWrite(PIN_RELAY_FAN, RELAY_ACTIVE);
      digitalWrite(PIN_RELAY_PUMP, RELAY_INACTIVE);

      if (!buzzerMuted) {
        digitalWrite(PIN_BUZZER, HIGH);
      } else {
        digitalWrite(PIN_BUZZER, LOW);
      }

      refreshLcdBuffer("! GAS LEAKAGE !", "EXHAUST FAN ON");

      // One-Shot SMS Dispatch on State Entry
      if (previousState != STATE_GAS_LEAK) {
        sendEmergencySms("EMERGENCY: Toxic Gas/Smoke Leakage detected (>400 ADC)! Exhaust Fan Active. Evacuate immediately!");
      }
      break;

    case STATE_FIRE_EMERGENCY:
      // Status LEDs: Red ON, Green/Blue OFF
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_BLUE, LOW);
      digitalWrite(PIN_LED_RED, HIGH);

      // Actuators: Sprinkler Pump Active (LOW)
      digitalWrite(PIN_RELAY_PUMP, RELAY_ACTIVE);
      
      // CRITICAL SAFETY INTERLOCK: Exhaust fan is strictly FORCED OFF to prevent feeding fresh oxygen to flames!
      digitalWrite(PIN_RELAY_FAN, RELAY_INACTIVE);

      if (!buzzerMuted) {
        digitalWrite(PIN_BUZZER, HIGH);
      } else {
        digitalWrite(PIN_BUZZER, LOW);
      }

      refreshLcdBuffer("! FIRE DETECTED !", "SPRINKLER ON");

      // One-Shot SMS Dispatch on State Entry
      if (previousState != STATE_FIRE_EMERGENCY) {
        sendEmergencySms("CRITICAL HAZARD: Active combustion flame detected at Kitchen Station! Water Sprinkler Engaged!");
      }
      break;
  }

  previousState = currentState;
}

/*
 * ====================================================================================================
 * I2C LCD HARDWARE RECOVERY ROUTINE
 * ====================================================================================================
 */
void bootLcdScreen() {
  Wire.begin();
  lcd.init();
  lcd.backlight();
  lcd.clear();
}

void refreshLcdBuffer(const char* line1, const char* line2) {
  static char prev1[17] = "";
  static char prev2[17] = "";

  if (strcmp(prev1, line1) != 0) {
    lcd.setCursor(0, 0);
    lcd.print("                ");
    lcd.setCursor(0, 0);
    lcd.print(line1);
    strncpy(prev1, line1, sizeof(prev1));
  }

  if (strcmp(prev2, line2) != 0) {
    lcd.setCursor(0, 1);
    lcd.print("                ");
    lcd.setCursor(0, 1);
    lcd.print(line2);
    strncpy(prev2, line2, sizeof(prev2));
  }
}

/*
 * ====================================================================================================
 * TACTILE MUTE BUTTON INTERRUPT-EMULATING DEBOUNCE
 * ====================================================================================================
 */
void pollMutePushbutton() {
  int currentRead = digitalRead(PIN_BTN_MUTE);

  if (currentRead != lastBtnState) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (currentRead == LOW && lastBtnState == HIGH) {
      buzzerMuted = !buzzerMuted;
      if (buzzerMuted) {
        digitalWrite(PIN_BUZZER, LOW);
      } else if (currentState != STATE_SAFE) {
        digitalWrite(PIN_BUZZER, HIGH);
      }
    }
  }

  lastBtnState = currentRead;
}

/*
 * ====================================================================================================
 * GSM SIM800L CELLULAR DRIVER & AT TELEMETRY
 * ====================================================================================================
 */
void initGsmModem() {
  gsmSerial.println("AT");
  delay(300);
  gsmSerial.println("AT+CMGF=1");          // Select SMS Text Mode
  delay(300);
  gsmSerial.println("AT+CNMI=1,2,0,0,0");  // New message direct indication
  delay(300);
}

void sendEmergencySms(const char* message) {
  gsmSerial.print("AT+CMGS=\"");
  gsmSerial.print(EMERGENCY_PHONE);
  gsmSerial.println("\"");
  delay(400);

  gsmSerial.print(message);
  delay(200);

  // Send ASCII 26 (Ctrl+Z) to finalize and transmit SMS packet
  gsmSerial.write(26);
  delay(800);

  // Transmit dispatch event confirmation to USB console
  Serial.print("{\"event\":\"SMS_DISPATCHED\",\"recipient\":\"");
  Serial.print(EMERGENCY_PHONE);
  Serial.print("\",\"message\":\"");
  Serial.print(message);
  Serial.println("\"}");
}

/*
 * ====================================================================================================
 * TELEMETRY SERIAL STREAM
 * ====================================================================================================
 */
void transmitTelemetry(int gasVal, bool flameDetected, float temp, float hum) {
  // Structured JSON format for web parser
  Serial.print("{\"gas\":");
  Serial.print(gasVal);
  Serial.print(",\"flame\":");
  Serial.print(flameDetected ? "true" : "false");
  Serial.print(",\"temp\":");
  Serial.print(temp, 1);
  Serial.print(",\"hum\":");
  Serial.print(hum, 1);
  Serial.print(",\"state\":");
  Serial.print((int)currentState);
  Serial.print(",\"muted\":");
  Serial.print(buzzerMuted ? "true" : "false");
  Serial.print(",\"fan\":");
  Serial.print((currentState == STATE_GAS_LEAK) ? "\"ON\"" : "\"OFF\"");
  Serial.print(",\"pump\":");
  Serial.print((currentState == STATE_FIRE_EMERGENCY) ? "\"ON\"" : "\"OFF\"");
  Serial.println("}");
}
