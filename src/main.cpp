#include <Arduino.h>
#include <SoftwareSerial.h>

// ============================================================
// Low-traffic design: instead of streaming lines constantly, the Arduino sends
// ONE small snapshot of everything ("S" + 4 hex digits + 1 checksum digit,
// e.g. "S00A1B") only when something changes, plus a heartbeat every
// HEARTBEAT_MS so the PC stays in sync and can detect a dropped link.
// All repeating / holding / mouse movement is done on the PC side.
// ============================================================

// ---- HC-05 Bluetooth (SoftwareSerial) ----
// NOTE: set these to whatever pins your HC-05 is actually wired to.
// HC-05 TX -> BT_RX_PIN
// HC-05 RX <- BT_TX_PIN (through a voltage divider)
const int BT_RX_PIN = A3;
const int BT_TX_PIN = A2;
const long BT_BAUD = 9600;       // HC-05 default data baud rate
SoftwareSerial bt(BT_RX_PIN, BT_TX_PIN);

// Mirror snapshots to USB serial for debugging (0 = Bluetooth only).
#define DEBUG_USB 0

// ---- Bit positions in the state word (must match the Python script) ----
enum StateBit {
  B_TRIANGLE = 0,
  B_CIRCLE   = 1,
  B_X        = 2,
  B_SQUARE   = 3,
  B_UP       = 4,
  B_RIGHT    = 5,
  B_DOWN     = 6,
  B_LEFT     = 7,
  B_SHOOT    = 8,
  B_AIM      = 9,   // latching switch: bit stays set while the switch is on
  B_JLEFT    = 10,
  B_JRIGHT   = 11,
  B_JUP      = 12,
  B_JDOWN    = 13,
  B_JSW      = 14   // joystick push-switch
};

uint16_t state = 0;

// ---- Digital inputs (wired between pin and GND, INPUT_PULLUP) ----
const unsigned long DEBOUNCE_MS = 25;  // input must be steady this long to count

struct Input {
  uint8_t pin;
  uint8_t bit;
  bool stable;               // debounced state (true = pressed / switch on)
  bool lastReading;          // raw reading from the previous pass
  unsigned long lastChange;  // when the raw reading last flipped
};

Input inputs[] = {
  {4,  B_TRIANGLE, false, false, 0},
  {5,  B_CIRCLE,   false, false, 0},
  {6,  B_X,        false, false, 0},
  {7,  B_SQUARE,   false, false, 0},
  {9,  B_UP,       false, false, 0},
  {10, B_RIGHT,    false, false, 0},
  {11, B_DOWN,     false, false, 0},
  {12, B_LEFT,     false, false, 0},
  {13, B_SHOOT,    false, false, 0},
  {3,  B_AIM,      false, false, 0},   // aim switch
  {8,  B_JSW,      false, false, 0},   // joystick push-switch
};
const int NUM_INPUTS = sizeof(inputs) / sizeof(inputs[0]);

// ---- Joystick (analog) ----
const int JOY_X_PIN = A0;
const int JOY_Y_PIN = A1;
const int JOY_LOW = 300;    // below this = pushed toward low end
const int JOY_HIGH = 700;   // above this = pushed toward high end
const int JOY_HYST = 40;    // must come back this far past a threshold to release

int xDir = 0, yDir = 0;     // -1, 0, +1

int axisDir(int v, int cur) {
  if (cur < 0 && v < JOY_LOW + JOY_HYST) return -1;
  if (cur > 0 && v > JOY_HIGH - JOY_HYST) return 1;
  if (v < JOY_LOW) return -1;
  if (v > JOY_HIGH) return 1;
  return 0;
}

void setBit(uint8_t bit, bool on) {
  if (on) state |= (1u << bit);
  else state &= ~(1u << bit);
}

void update_inputs() {
  unsigned long now = millis();
  for (int i = 0; i < NUM_INPUTS; i++) {
    Input &in = inputs[i];
    bool reading = (digitalRead(in.pin) == LOW);   // LOW = pressed (pull-up)

    if (reading != in.lastReading) {
      in.lastChange = now;                         // changed: restart debounce
      in.lastReading = reading;
    }
    if ((now - in.lastChange) >= DEBOUNCE_MS && reading != in.stable) {
      in.stable = reading;
      setBit(in.bit, in.stable);
    }
  }
}

void update_joystick() {
  int x = analogRead(JOY_X_PIN);
  int y = analogRead(JOY_Y_PIN);
  xDir = axisDir(x, xDir);
  yDir = axisDir(y, yDir);
  setBit(B_JLEFT,  xDir < 0);
  setBit(B_JRIGHT, xDir > 0);
  setBit(B_JUP,    yDir < 0);
  setBit(B_JDOWN,  yDir > 0);
}

// ---- Sending ----
const unsigned long HEARTBEAT_MS = 100;  // resend the snapshot at least this often
unsigned long lastSend = 0;

void sendState() {
  uint8_t chk = ((state >> 12) ^ (state >> 8) ^ (state >> 4) ^ state) & 0xF;
  char buf[10];
  snprintf(buf, sizeof(buf), "S%04X%X", state, chk);
  bt.println(buf);
#if DEBUG_USB
  Serial.println(buf);
#endif
}

void setup() {
  Serial.begin(9600);   // USB (debug)
  bt.begin(BT_BAUD);    // HC-05

  pinMode(JOY_X_PIN, INPUT);
  pinMode(JOY_Y_PIN, INPUT);
  for (int i = 0; i < NUM_INPUTS; i++) {
    pinMode(inputs[i].pin, INPUT_PULLUP);
  }
}

void loop() {
  uint16_t prev = state;
  update_inputs();
  update_joystick();

  unsigned long now = millis();
  if (state != prev || (now - lastSend) >= HEARTBEAT_MS) {
    lastSend = now;
    sendState();
  }

  delay(2);
}