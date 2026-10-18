#include <Arduino.h>
#include <SoftwareSerial.h>

// ---- HC-05 Bluetooth (on SoftwareSerial, since pins 0/1 are used by USB) ----
// HC-05 TX  -> Arduino pin 2   (BT_RX_PIN)
// HC-05 RX  <- Arduino A2      (BT_TX_PIN)  through a voltage divider (see notes)
const int BT_RX_PIN = 2;
const int BT_TX_PIN = A2;
const long BT_BAUD = 9600;       // HC-05 default data baud rate
SoftwareSerial bt(BT_RX_PIN, BT_TX_PIN);

// Also mirror everything to USB serial so you can still debug in the Serial Monitor.
// Set to 0 to send over Bluetooth only.
#define DEBUG_USB 0

void sendLine(const char* s) {
  bt.println(s);
#if DEBUG_USB
  Serial.println(s);
#endif
}

// joystick
const int JOY_X_PIN = A0;  // X-axis analog input
const int JOY_Y_PIN = A1;  // Y-axis analog input
const int SWITCH_PIN = 8;

// Non-blocking timer variable for streaming
unsigned long lastPrintTime = 0;
const unsigned long PRINT_INTERVAL = 50; // Stream joystick data every 50ms

// pushbuttons (wired between pin and GND, using INPUT_PULLUP)
const unsigned long DEBOUNCE_MS = 25;  // input must be stable this long to count

// Shape buttons: tap = one output, hold past the delay = slow repeat
const unsigned long SHAPE_HOLD_DELAY_MS = 600;
const unsigned long SHAPE_REPEAT_MS = 150;

// Direction buttons: continuous. Output starts immediately and keeps coming
// every DIR_REPEAT_MS for as long as the button is held (no hold delay).
const unsigned long DIR_HOLD_DELAY_MS = 0;
const unsigned long DIR_REPEAT_MS = 20;  // ~50 outputs/sec (lower = faster)

struct Button {
  const char* name;
  uint8_t pin;
  unsigned long holdDelay;  // how long to hold before repeating starts
  unsigned long repeatMs;   // time between repeats once repeating
  bool stableState;         // debounced state: true = pressed
  bool lastReading;         // raw reading from the previous pass
  unsigned long lastChange; // when the raw reading last flipped
  unsigned long nextRepeat; // when the next repeat is due while held
};

Button buttons[] = {
  // shapes
  {"TRIANGLE", 4,  SHAPE_HOLD_DELAY_MS, SHAPE_REPEAT_MS, false, false, 0, 0},
  {"CIRCLE",   5,  SHAPE_HOLD_DELAY_MS, SHAPE_REPEAT_MS, false, false, 0, 0},
  {"X",        6,  DIR_HOLD_DELAY_MS,   DIR_REPEAT_MS,   false, false, 0, 0},  // continuous
  {"SQUARE",   7,  SHAPE_HOLD_DELAY_MS, SHAPE_REPEAT_MS, false, false, 0, 0},
  // directions (continuous)
  {"UP",       9,  DIR_HOLD_DELAY_MS,   DIR_REPEAT_MS,   false, false, 0, 0},
  {"RIGHT",    10, DIR_HOLD_DELAY_MS,   DIR_REPEAT_MS,   false, false, 0, 0},
  {"DOWN",     11, DIR_HOLD_DELAY_MS,   DIR_REPEAT_MS,   false, false, 0, 0},
  {"LEFT",     12, DIR_HOLD_DELAY_MS,   DIR_REPEAT_MS,   false, false, 0, 0},
  // shoot (continuous)
  {"SHOOT",    13, DIR_HOLD_DELAY_MS,   DIR_REPEAT_MS,   false, false, 0, 0},
};
const int NUM_BUTTONS = sizeof(buttons) / sizeof(buttons[0]);

void read_joystick() {
  if (millis() - lastPrintTime >= PRINT_INTERVAL) {
    lastPrintTime = millis();

    int xValue = analogRead(JOY_X_PIN);
    int yValue = analogRead(JOY_Y_PIN);
    int switchValue = digitalRead(SWITCH_PIN);

    char line[24];
    snprintf(line, sizeof(line), "%d,%d,%d", xValue, yValue, switchValue);
    sendLine(line);
  }
}

// Sends the button name once per press, then repeats it while held
// (after holdDelay, every repeatMs). Direction buttons have holdDelay = 0,
// so they stream continuously from the moment they are pressed.
void read_pushbtn() {
  unsigned long now = millis();

  for (int i = 0; i < NUM_BUTTONS; i++) {
    Button &b = buttons[i];
    bool reading = (digitalRead(b.pin) == LOW);  // LOW = pressed (pull-up)

    if (reading != b.lastReading) {
      b.lastChange = now;       // raw signal changed, restart the debounce timer
      b.lastReading = reading;
    }

    if ((now - b.lastChange) >= DEBOUNCE_MS && reading != b.stableState) {
      b.stableState = reading;  // signal has been steady long enough
      if (reading) {
        sendLine(b.name);                // the first press event
        b.nextRepeat = now + b.holdDelay + b.repeatMs;
        if (b.holdDelay > 0) b.nextRepeat = now + b.holdDelay;
      }
    }

    // still held: keep repeating
    if (b.stableState && now >= b.nextRepeat) {
      sendLine(b.name);
      b.nextRepeat = now + b.repeatMs;
    }
  }
}

// Aim switch (a latching switch, NOT a pushbutton): wired between pin 3 and GND.
// Switch closed = aiming. Sends "AIM_ON" / "AIM_OFF" when it changes, and
// re-sends the current state every AIM_RESEND_MS so the PC always catches up
// (Bluetooth doesn't reset the Arduino on connect like USB does, and
// wireless messages can occasionally get lost).
const int AIM_PIN = 3;
const unsigned long AIM_RESEND_MS = 250;
bool aimStable = false;         // debounced state: true = switch on
bool aimLastReading = false;
unsigned long aimLastChange = 0;
unsigned long aimLastSent = 0;

void read_aim_switch() {
  unsigned long now = millis();
  bool reading = (digitalRead(AIM_PIN) == LOW);  // LOW = switch closed (pull-up)

  if (reading != aimLastReading) {
    aimLastChange = now;
    aimLastReading = reading;
  }

  bool changed = false;
  if ((now - aimLastChange) >= DEBOUNCE_MS && reading != aimStable) {
    aimStable = reading;
    changed = true;
  }

  if (changed || (now - aimLastSent) >= AIM_RESEND_MS) {
    aimLastSent = now;
    sendLine(aimStable ? "AIM_ON" : "AIM_OFF");
  }
}

void setup() {
  Serial.begin(9600);   // USB (debug)
  bt.begin(BT_BAUD);   // HC-05

  pinMode(JOY_X_PIN, INPUT);
  pinMode(JOY_Y_PIN, INPUT);
  pinMode(SWITCH_PIN, INPUT_PULLUP);
  pinMode(AIM_PIN, INPUT_PULLUP);

  for (int i = 0; i < NUM_BUTTONS; i++) {
    pinMode(buttons[i].pin, INPUT_PULLUP);
  }
}

void loop() {
  read_joystick();
  read_pushbtn();
  read_aim_switch();

  delay(5);
}