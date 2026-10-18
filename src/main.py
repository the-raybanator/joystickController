import ctypes
import time
import serial
import serial.tools.list_ports
import keyboard

MOUSEEVENTF_MOVE = 0x0001   # Windows relative-move flag
MOUSEEVENTF_WHEEL = 0x0800  # Windows mouse-wheel flag
WHEEL_DELTA = 120           # one "notch" of the scroll wheel

# Windows mouse-button flags: (down, up)
MOUSE_BUTTON_FLAGS = {
    "left":  (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
}
mouse_held = {"left": False, "right": False}

# ============================================================
# >>> SHOOT BUTTON (continuous) <<<
# While SHOOT is held, this mouse button is held down (left click = fire).
# It's released ~0.1 s after the Arduino stops sending SHOOT.
# ============================================================
SHOOT_MOUSE_BUTTON = "left"
SHOOT_TIMEOUT = 0.1  # seconds without a SHOOT line = released

# ============================================================
# >>> AIM SWITCH <<<
# AIM_ON  -> right mouse button held down
# AIM_OFF -> right mouse button released
# ============================================================
AIM_MOUSE_BUTTON = "right"

# ============================================================
# >>> SCROLL BUTTONS <<<
# Each press scrolls the mouse wheel by this many notches.
# +1 = one notch up (previous hotbar slot in most games), -1 = one notch down.
# ============================================================
SCROLL_MAPPINGS = {
    "TRIANGLE": +1,
}

BAUD_RATE = 9600   # must match Serial.begin in the sketch
LOW, HIGH = 300, 700

REPEAT_DELAY = 0.4      # joystick: seconds before repeating starts (like a real keyboard)
REPEAT_INTERVAL = 0.03  # joystick: seconds between repeats once it starts

# ============================================================
# >>> EDIT YOUR PUSHBUTTON MAPPINGS HERE <<<
# Left side = the name the Arduino prints, right side = key to press.
# Use any key name the `keyboard` library understands
# (e.g. 'e', 'q', 'space', 'enter', 'ctrl', 'esc', 'f', '1', ...).
# Set a button to None to disable it.
# ============================================================
BUTTON_MAPPINGS = {
    "CIRCLE":   "ctrl",
    "X":        "space",
    "SQUARE":   "e",
}

# Buttons that are continuous in the Arduino sketch (it streams their name
# every ~20 ms while held). For these, the key is held down for as long as
# names keep arriving, and released once they stop.
CONTINUOUS_BUTTONS = {"X"}
CONTINUOUS_TIMEOUT = 0.1  # seconds without a name = button released

# ============================================================
# >>> MOUSE MOVEMENT BUTTONS <<<
# Each press moves the pointer by MOUSE_STEP pixels (dx, dy).
# Holding the button repeats (speed is set in the Arduino sketch).
# Screen coordinates: +x = right, +y = down.
# ============================================================
MOUSE_STEP = 15  # pixels per press/repeat -- tune sensitivity here later
MOUSE_MAPPINGS = {
    "UP":    (0, -MOUSE_STEP),
    "RIGHT": (MOUSE_STEP, 0),
    "DOWN":  (0, MOUSE_STEP),
    "LEFT":  (-MOUSE_STEP, 0),
}

# The Arduino prints a button's name once per press (and repeats it only if you
# hold the button for over half a second). Each name received = one key tap.
# Hold delay / repeat speed are set in the Arduino sketch (HOLD_DELAY_MS,
# REPEAT_INTERVAL_MS).
BUTTON_TAP_DURATION = 0.03  # how long each key tap is held down (helps games register it)

# Joystick key mappings (edit if you want different keys)
JOY_LEFT, JOY_RIGHT, JOY_UP, JOY_DOWN = 'a', 'd', 'w', 's'
JOY_SWITCH = 'shift'


def find_arduino():
    for p in serial.tools.list_ports.comports():
        text = f"{p.description} {p.manufacturer}"
        if any(k in text for k in ("Arduino", "CH340", "USB-SERIAL")):
            return p.device
    return None


port = find_arduino()
if port is None:
    print("No Arduino found. Is it plugged in, and is the serial monitor closed?")
    raise SystemExit

print(f"Connecting on {port}...")
ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
time.sleep(2)
ser.reset_input_buffer()
print("Connected. Focus Notepad or a game and move the stick.")

# every key we might press
keys = {JOY_LEFT, JOY_RIGHT, JOY_UP, JOY_DOWN, JOY_SWITCH}
keys.update(k for k in BUTTON_MAPPINGS.values() if k)

held = {k: False for k in keys}
next_repeat = {k: 0.0 for k in keys}   # when the next repeat is due


def update_key(key, should_press, repeat=True):
    now = time.monotonic()
    if should_press:
        if not held[key]:
            # first press
            keyboard.press(key)
            held[key] = True
            next_repeat[key] = now + REPEAT_DELAY
        elif repeat and now >= next_repeat[key]:
            # still held: send another key-down, like auto-repeat
            keyboard.press(key)
            next_repeat[key] = now + REPEAT_INTERVAL
    elif held[key]:
        keyboard.release(key)
        held[key] = False


def tap_key(key):
    """Press and release a key once."""
    keyboard.press(key)
    time.sleep(BUTTON_TAP_DURATION)
    keyboard.release(key)


def move_mouse(dx, dy):
    """Move the pointer relative to its current position (Windows)."""
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)


def mouse_down(button):
    if not mouse_held[button]:
        ctypes.windll.user32.mouse_event(MOUSE_BUTTON_FLAGS[button][0], 0, 0, 0, 0)
        mouse_held[button] = True


def mouse_up(button):
    if mouse_held[button]:
        ctypes.windll.user32.mouse_event(MOUSE_BUTTON_FLAGS[button][1], 0, 0, 0, 0)
        mouse_held[button] = False


def scroll(notches):
    """Scroll the mouse wheel. Positive = up, negative = down."""
    ctypes.windll.user32.mouse_event(
        MOUSEEVENTF_WHEEL, 0, 0, (notches * WHEEL_DELTA) & 0xFFFFFFFF, 0
    )


def handle_line(line):
    """Parse one line from the Arduino and update state."""
    global x, y, sw
    if not line:
        return
    if line == "AIM_ON":
        mouse_down(AIM_MOUSE_BUTTON)
        return
    if line == "AIM_OFF":
        mouse_up(AIM_MOUSE_BUTTON)
        return
    if line == "SHOOT":
        # keep the button held; the main loop releases it when SHOOT stops arriving
        shoot_last_seen[0] = time.monotonic()
        mouse_down(SHOOT_MOUSE_BUTTON)
        return
    if line in SCROLL_MAPPINGS:
        # scroll button, e.g. "TRIANGLE" -> one wheel notch
        scroll(SCROLL_MAPPINGS[line])
        return
    if line in MOUSE_MAPPINGS:
        # direction button, e.g. "UP" -> nudge the pointer
        dx, dy = MOUSE_MAPPINGS[line]
        move_mouse(dx, dy)
        return
    if line in BUTTON_MAPPINGS:
        # button line, e.g. "CIRCLE" -> one tap of the mapped key
        key = BUTTON_MAPPINGS[line]
        if key:
            if line in CONTINUOUS_BUTTONS:
                # hold the key down; the main loop releases it when names stop
                cont_last_seen[line] = time.monotonic()
                update_key(key, True, repeat=False)
            else:
                tap_key(key)
        return
    parts = line.split(",")
    if len(parts) == 3:
        try:
            x, y, sw = map(int, parts)
        except ValueError:
            pass


# latest joystick state, so repeats keep firing even between serial lines
x, y, sw = 512, 512, 1
# last time each continuous button's name arrived
cont_last_seen = {name: 0.0 for name in CONTINUOUS_BUTTONS}
# last time a SHOOT line arrived (list so handle_line can update it)
shoot_last_seen = [0.0]

try:
    while True:
        # wait for a line, then drain everything else that's already buffered
        handle_line(ser.readline().decode("utf-8", errors="ignore").strip())
        while ser.in_waiting:
            handle_line(ser.readline().decode("utf-8", errors="ignore").strip())

        # release continuous buttons once their names stop arriving
        now = time.monotonic()
        for name in CONTINUOUS_BUTTONS:
            key = BUTTON_MAPPINGS.get(name)
            if key and held[key] and now - cont_last_seen[name] > CONTINUOUS_TIMEOUT:
                update_key(key, False)

        # release SHOOT once its lines stop arriving
        if mouse_held[SHOOT_MOUSE_BUTTON] and now - shoot_last_seen[0] > SHOOT_TIMEOUT:
            mouse_up(SHOOT_MOUSE_BUTTON)

        # joystick
        update_key(JOY_LEFT, x < LOW)
        update_key(JOY_RIGHT, x > HIGH)
        update_key(JOY_UP, y < LOW)
        update_key(JOY_DOWN, y > HIGH)
        update_key(JOY_SWITCH, sw == 0)

except KeyboardInterrupt:
    pass
except serial.SerialException as e:
    print(f"Serial error: {e}")
finally:
    for k in keys:
        keyboard.release(k)
    for b in ("left", "right"):
        mouse_up(b)
    ser.close()
    print("Closed. All keys released.")