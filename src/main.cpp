#include <Arduino.h>

// joystick
const int JOY_X_PIN = A0;  // X-axis analog input
const int JOY_Y_PIN = A1;  // Y-axis analog input
const int SWITCH_PIN = 8;

// Non-blocking timer variable for Serial streaming
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
  // ensure Serial monitor doesn't crash
  if (millis() - lastPrintTime >= PRINT_INTERVAL) {
    lastPrintTime = millis();

    int xValue = analogRead(JOY_X_PIN);
    int yValue = analogRead(JOY_Y_PIN);
    int switchValue = digitalRead(SWITCH_PIN);

    Serial.print(xValue);
    Serial.print(",");
    Serial.print(yValue);
    Serial.print(",");
    Serial.println(switchValue);
  }
}

// Prints the button name once per press, then repeats it while held
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
        Serial.println(b.name);                // the first press event
        b.nextRepeat = now + b.holdDelay + b.repeatMs;
        if (b.holdDelay > 0) b.nextRepeat = now + b.holdDelay;
      }
    }

    // still held: keep repeating
    if (b.stableState && now >= b.nextRepeat) {
      Serial.println(b.name);
      b.nextRepeat = now + b.repeatMs;
    }
  }
}

// Aim switch (a latching switch, NOT a pushbutton): wired between pin 3 and GND.
// Switch closed = aiming. Sends "AIM_ON" once when switched on and
// "AIM_OFF" once when switched off.
const int AIM_PIN = 3;
bool aimStable = false;         // debounced state: true = switch on
bool aimLastReading = false;
unsigned long aimLastChange = 0;

void read_aim_switch() {
  unsigned long now = millis();
  bool reading = (digitalRead(AIM_PIN) == LOW);  // LOW = switch closed (pull-up)

  if (reading != aimLastReading) {
    aimLastChange = now;
    aimLastReading = reading;
  }

  if ((now - aimLastChange) >= DEBOUNCE_MS && reading != aimStable) {
    aimStable = reading;
    Serial.println(aimStable ? "AIM_ON" : "AIM_OFF");
  }
}

void setup() {
  Serial.begin(9600);

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