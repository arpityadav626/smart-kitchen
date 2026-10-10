/*
 * ====================================================================================================
 * PROJECT: Smart Kitchen Safety & Autonomous Hazard Mitigation System (SAFETY-FI 96X)
 * TARGET PLATFORM: Arduino Uno (ATmega328P @ 16 MHz)
 * ARCHITECTURE: Ultra-Fast 100ms Reactive FSM + 3-Second Sprinkler Latch + Instant Auto-Reset
 * AUTHOR: Arpit Yadav
 * ====================================================================================================
 *
 * HARDWARE PIN CONFIGURATION:
 * ----------------------------------------------------------------------------------------------------
 * - MQ-2 Gas / Smoke Sensor    -> Analog Pin A0
 * - IR Flame / Fire Sensor     -> Digital Pin 8 (Active-LOW: LOW = Fire Detected)
 * - DHT11 Temp & Humidity      -> Digital Pin 2
 * - Piezo Buzzer               -> Digital Pin 9
 * - Exhaust Fan Relay          -> Digital Pin 7 (Active-LOW Relay: LOW = Fan ON)
 * - Water Sprinkler Pump Relay -> Digital Pin 6 (Active-LOW Relay: LOW = Pump ON)
 * - Status LED Green (Safe)    -> Digital Pin 3
 * - Status LED Blue (Gas Leak) -> Digital Pin 4
 * - Status LED Green (Safe)    -> Digital Pin 3
 * - Status LED Blue (Gas Leak) -> Digital Pin 4
 * - Status LED Red (Fire)      -> Digital Pin 5
 * - I2C LCD Display (16x2)     -> Pin A4 (SDA), Pin A5 (SCL)
 * - Telemetry & Cloud Alerts   -> High-Speed USB Serial to Web Dashboard & Formspree Cloud Email
 * ====================================================================================================
 */

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>

// --- PIN ASSIGNMENTS ---
#define PIN_MQ_GAS         A0
#define PIN_FLAME          8
#define PIN_DHT            2
#define PIN_BUZZER         9
#define PIN_RELAY_FAN      7     // LOW = Fan ON, HIGH = Fan OFF
#define PIN_RELAY_PUMP     6     // LOW = Pump ON, HIGH = Pump OFF
#define PIN_LED_GREEN      3
#define PIN_LED_BLUE       4
#define PIN_LED_RED        5

// --- CONSTANTS & THRESHOLDS ---
#define DHTTYPE            DHT11
#define GAS_THRESHOLD      300   // Normal <= 300, Gas Leak > 300
#define RELAY_ACTIVE       LOW   // Active-LOW Trigger (GND ON)
#define RELAY_INACTIVE     HIGH  // Relay OFF (5V OFF)
#define PUMP_MIN_DURATION  5000  // Pump runs for at least 5 seconds to extinguish fire
#define GAS_MIN_DURATION   5000  // Exhaust fan runs for at least 5 seconds on gas detection

// --- SYSTEM STATES ---
enum SystemState {
  STATE_SAFE = 0,
  STATE_GAS_LEAK = 1,
  STATE_FIRE_EMERGENCY = 2
};

SystemState currentState = STATE_SAFE;

// --- SENSOR DRIVERS ---
DHT dht(PIN_DHT, DHTTYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2); // Default I2C Address: 0x27 (or 0x3F)

// Persistent Climate Memory
float lastTemp = 28.0;
float lastHum = 50.0;
int gasVal = 85;

// --- TIMERS ---
unsigned long lastFastCheck = 0;       // 100ms ultra-fast sensor & actuator loop
unsigned long lastTelemetryStream = 0; // 1000ms web stream
unsigned long lastDhtRead = 0;         // 2000ms DHT sensor read
unsigned long lastFireSeenTime = 0;    // 5-second minimum pump runtime latch
unsigned long lastGasSeenTime = 0;     // 5-second minimum fan runtime latch

// --- STRICT 5-SECOND FLAME TIMER ---
bool fireTimerActive = false;
unsigned long fireTimerStart = 0;
bool flameMustClear = false;

bool buzzerMuted = false;

// --- FUNCTION DECLARATIONS ---
void bootLcdScreen();
void refreshLcdBuffer(const char* line1, const char* line2);
void transmitTelemetry(int gasVal, bool flameDetected, float temp, float hum);

void setup() {
  // 1. Hardware Serial for USB Web Dashboard & Cloud Telemetry
  Serial.begin(9600);

  // 2. Inputs
  pinMode(PIN_MQ_GAS, INPUT);
  pinMode(PIN_FLAME, INPUT_PULLUP); // Internal pullup ensures stable 1 when idle

  // 3. Outputs
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_RELAY_FAN, OUTPUT);
  pinMode(PIN_RELAY_PUMP, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_BLUE, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);

  // Initial Safe State
  digitalWrite(PIN_RELAY_FAN, RELAY_INACTIVE);
  digitalWrite(PIN_RELAY_PUMP, RELAY_INACTIVE);
  digitalWrite(PIN_BUZZER, LOW);

  digitalWrite(PIN_LED_GREEN, HIGH);
  digitalWrite(PIN_LED_BLUE, LOW);
  digitalWrite(PIN_LED_RED, LOW);

  // 🔍 4. BOOT SELF-TEST: 0.4s Pump Relay Click Confirmation!
  digitalWrite(PIN_RELAY_PUMP, RELAY_ACTIVE);   // Click ON (Confirms Pin 6 connection!)
  delay(400);
  digitalWrite(PIN_RELAY_PUMP, RELAY_INACTIVE); // Click OFF

  // 5. Initialize Sensors & LCD
  dht.begin();
  bootLcdScreen();
  refreshLcdBuffer("SAFETY-FI 96X   ", "INITIALIZING... ");
  delay(600);

  refreshLcdBuffer("SYSTEM ONLINE   ", "SENTINEL ARMED  ");
  delay(800);
}

void loop() {
  unsigned long currentMillis = millis();

  // Web Dashboard Mute Command check
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command == "MUTE") {
      buzzerMuted = !buzzerMuted;
      if (buzzerMuted) digitalWrite(PIN_BUZZER, LOW);
    }
  }

  // 1. DHT Climate Reading (Every 2 seconds)
  if (currentMillis - lastDhtRead >= 2000) {
    lastDhtRead = currentMillis;
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    if (!isnan(t) && t > 0.0 && t < 90.0) lastTemp = t;
    if (!isnan(h) && h > 0.0 && h <= 100.0) lastHum = h;
  }

  // 2. ULTRA-FAST 100ms REACTIVE CONTROL LOOP
  if (currentMillis - lastFastCheck >= 100) {
    lastFastCheck = currentMillis;

    gasVal = analogRead(PIN_MQ_GAS);

    // --- INSTANT FLAME SENSE + STRICT 5-SECOND ONE-SHOT TIMER ---
    int flameRaw = digitalRead(PIN_FLAME);

    // If flame is sensed (Pin 8 LOW) and timer is not currently running
    if (flameRaw == LOW) {
      if (!fireTimerActive && !flameMustClear) {
        fireTimerActive = true;
        fireTimerStart = currentMillis;
        flameMustClear = true; // Lock until flame clears to prevent non-stop loop
      }
    } else {
      // Flame moved away (Pin 8 HIGH) -> arm ready for next trigger
      flameMustClear = false;
    }

    // STRICT 5-SECOND TIMER: Exactly 5000ms, then TURANT BAND!
    if (fireTimerActive) {
      if (currentMillis - fireTimerStart >= 5000) {
        fireTimerActive = false; // 5 seconds expired -> IMMEDIATELY SHUT OFF!
        fireTimerStart = 0;
      }
    }

    bool fireActiveOrLatched = fireTimerActive;

    // Check if gas is active OR within the 5-second exhaust fan run latch
    bool gasActiveOrLatched = (gasVal > GAS_THRESHOLD || ((currentMillis - lastGasSeenTime) < GAS_MIN_DURATION && lastGasSeenTime > 0));

    // ====================================================================
    // FINITE STATE MACHINE WITH 5-SECOND PUMP/FAN LATCH & AUTO-RESET
    // ====================================================================

    SystemState previousState = currentState;

    // CASE 1: ACTIVE FIRE HAZARD (Runs for minimum 5 seconds)
    if (fireActiveOrLatched) {
      currentState = STATE_FIRE_EMERGENCY;

      // Actuators: Water Sprinkler ON, Fan Forced OFF
      digitalWrite(PIN_RELAY_PUMP, RELAY_ACTIVE);   // PUMP SOLID ON (Pin 6 -> LOW)!
      digitalWrite(PIN_RELAY_FAN, RELAY_INACTIVE);  // FAN OFF (Prevents feeding fire)
      
      // LEDs & Siren
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_BLUE, LOW);
      digitalWrite(PIN_LED_RED, HIGH);
      if (!buzzerMuted) digitalWrite(PIN_BUZZER, HIGH);

      // Instant LCD Alert
      char l1[17] = "! FIRE ALERT !  ";
      char l2[17];
      snprintf(l2, sizeof(l2), "T:%dC PUMP:ACTIVE", (int)lastTemp);
      refreshLcdBuffer(l1, l2);
    }

    // CASE 2: GAS / SMOKE LEAKAGE HAZARD (Runs for minimum 5 seconds)
    else if (gasActiveOrLatched) {
      currentState = STATE_GAS_LEAK;

      // Actuators: Exhaust Fan ON, Pump OFF
      digitalWrite(PIN_RELAY_FAN, RELAY_ACTIVE);    // EXHAUST FAN ENGAGED!
      digitalWrite(PIN_RELAY_PUMP, RELAY_INACTIVE); // PUMP OFF

      // LEDs & Siren
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_BLUE, HIGH);
      digitalWrite(PIN_LED_RED, LOW);
      if (!buzzerMuted) digitalWrite(PIN_BUZZER, HIGH);

      // Instant LCD Alert
      char l1[17] = "! GAS LEAKAGE ! ";
      char l2[17];
      snprintf(l2, sizeof(l2), "G:%-4d FAN:ACTIVE", gasVal);
      refreshLcdBuffer(l1, l2);
    }

    // CASE 3: SAFE STANDBY (AUTOMATIC INSTANT RESET AFTER 3-SECOND LATCH EXPIRES!)
    else {
      currentState = STATE_SAFE;
      buzzerMuted = false;

      // Actuators: Relays & Buzzer Instantly Turned OFF
      digitalWrite(PIN_RELAY_FAN, RELAY_INACTIVE);
      digitalWrite(PIN_RELAY_PUMP, RELAY_INACTIVE); // PUMP OFF (Pin 6 -> HIGH)
      digitalWrite(PIN_BUZZER, LOW);

      // Status LEDs: Green ON, others OFF
      digitalWrite(PIN_LED_GREEN, HIGH);
      digitalWrite(PIN_LED_BLUE, LOW);
      digitalWrite(PIN_LED_RED, LOW);

      // Permanent Normal Telemetry Display
      int tInt = (int)lastTemp;
      int tDec = (int)((lastTemp - tInt) * 10);
      if (tDec < 0) tDec = -tDec;
      int hInt = (int)lastHum;

      char l1[17];
      char l2[17];
      snprintf(l1, sizeof(l1), "T:%d.%dC  H:%d%%   ", tInt, tDec, hInt);
      snprintf(l2, sizeof(l2), "GAS:%-4d  [SAFE]", gasVal);
      refreshLcdBuffer(l1, l2);
    }

    // ⚡ INSTANT TELEMETRY PUSH: If state transitions (fire tripped, gas tripped, or reset), push immediately (0ms lag)!
    if (currentState != previousState) {
      transmitTelemetry(gasVal, fireActiveOrLatched, lastTemp, lastHum);
      lastTelemetryStream = currentMillis;
    }
  }

  // 3. Web Telemetry Stream to USB (High-speed 200ms = 5 Hz for ultra-smooth dashboard gauges)
  if (currentMillis - lastTelemetryStream >= 200) {
    lastTelemetryStream = currentMillis;
    bool fireActiveOrLatched = ((digitalRead(PIN_FLAME) == LOW) || ((currentMillis - lastFireSeenTime) < PUMP_MIN_DURATION && lastFireSeenTime > 0));
    transmitTelemetry(gasVal, fireActiveOrLatched, lastTemp, lastHum);
  }
}

// ====================================================================
// LCD DRIVER (Flicker-Free Direct Overwrite)
// ====================================================================
void bootLcdScreen() {
  Wire.begin();
  lcd.init();
  lcd.backlight();
  lcd.clear();
}

void refreshLcdBuffer(const char* line1, const char* line2) {
  lcd.setCursor(0, 0);
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);
}


// ====================================================================
// LIVE TELEMETRY TRANSMISSION (To Web Dashboard & Serial Monitor)
// ====================================================================
void transmitTelemetry(int gasVal, bool flameDetected, float temp, float hum) {
  int flameRaw = digitalRead(PIN_FLAME);
  Serial.print("{\"gas\":");
  Serial.print(gasVal);
  Serial.print(",\"flame\":");
  Serial.print(flameDetected ? "true" : "false");
  Serial.print(",\"flame_raw\":");
  Serial.print(flameRaw);
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
