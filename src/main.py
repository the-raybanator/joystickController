import ctypes
import time
import serial
import serial.tools.list_ports
import keyboard

# ============================================================
# How this works (low-lag design)
# The Arduino sends one small snapshot of ALL buttons ("S....") whenever
# something changes, plus a heartbeat ~10x/second. This script compares each
# snapshot with the previous one to find presses/releases, and does all the
# holding, repeating and mouse movement itself with accurate timers.
# ============================================================

user32 = ctypes.windll.user32

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
# >>> CONNECTION <<<
# This script ONLY talks to the HC-05 over Bluetooth. USB serial ports are
# never used (they're refused even if you type one in).
#
# PORT = None   -> auto-detect: tries each paired "Standard Serial over
#                  Bluetooth link" port and uses the one that sends data
# PORT = "COM5" -> use that specific Bluetooth port (must be a Bluetooth one)
# ============================================================
BAUD_RATE = 9600     # must match the sketch (HC-05 default is 9600)
PORT = None
PROBE_SECONDS = 5    # how long to listen on each Bluetooth port when auto-detecting

# The Arduino sends a snapshot at least every 0.1 s. If nothing arrives for
# this long (Bluetooth dropped), everything is released so nothing sticks.
LINK_TIMEOUT = 0.6   # seconds

# ============================================================
# >>> EDIT YOUR BUTTON ACTIONS HERE <<<
# name: (action, argument)
#
#   "tap"    key  -> taps the key on press; repeats if held (see TAP_* below)
#   "hold"   key  -> holds the key down for as long as the button is held
#   "scroll" n    -> scrolls the wheel n notches on press (+1 up, -1 down);
#                    repeats if held
#   "move"   (dx, dy) -> moves the pointer continuously while held
#                    (screen coordinates: +x right, +y down)
#   "click"  "left"/"right" -> holds that mouse button while held
#                    (works for the AIM switch too: on = held)
#
# Key names are anything the `keyboard` library understands
# ('e', 'q', 'space', 'enter', 'ctrl', 'esc', 'f', '1', ...).
# ============================================================
BUTTON_ACTIONS = {
    "TRIANGLE": ("scroll", +1),
    "CIRCLE":   ("tap", "ctrl"),
    "X":        ("hold", "space"),
    "SQUARE":   ("tap", "e"),
    "UP":       ("move", (0, -1)),
    "RIGHT":    ("move", (1, 0)),
    "DOWN":     ("move", (0, 1)),
    "LEFT":     ("move", (-1, 0)),
    "SHOOT":    ("click", "left"),
    "AIM":      ("click", "right"),
}

# --- tap / scroll buttons ---
TAP_DURATION = 0.03         # how long each key tap is held down (helps games register it)
TAP_AUTO_REPEAT = True      # False = exactly one action per press, never repeat
TAP_HOLD_DELAY = 0.6        # hold this long before repeating starts
TAP_REPEAT_INTERVAL = 0.15  # seconds between repeats once repeating

# --- pointer movement buttons ---
MOUSE_STEP = 15              # pixels per step -- raise this for faster turning
MOUSE_INTERVAL = 0.02       # seconds between steps (0.02 = 50 steps/s)

# --- joystick: direction -> key ---
JOY_KEYS = {
    "JLEFT":  "a",
    "JRIGHT": "d",
    "JUP":    "w",
    "JDOWN":  "s",
    "JSW":    "shift",   # pressing the stick in
}
JOY_REPEAT_DELAY = 0.4      # like a real keyboard: delay before repeating
JOY_REPEAT_INTERVAL = 0.03  # then repeat this often

# Bit positions in the Arduino's snapshot (must match the sketch)
BITS = {
    "TRIANGLE": 0, "CIRCLE": 1, "X": 2, "SQUARE": 3,
    "UP": 4, "RIGHT": 5, "DOWN": 6, "LEFT": 7,
    "SHOOT": 8, "AIM": 9,
    "JLEFT": 10, "JRIGHT": 11, "JUP": 12, "JDOWN": 13, "JSW": 14,
}

# ------------------------------------------------------------
# Connection
# ------------------------------------------------------------


def bluetooth_ports():
    """COM ports that Windows lists as Bluetooth serial links (never USB)."""
    return [
        p for p in serial.tools.list_ports.comports()
        if "bluetooth" in f"{p.description}".lower() or "BTHENUM" in f"{p.hwid}".upper()
    ]


def parse_snapshot(line):
    """Return the state bitmask from a line like 'S00A1B', or None if invalid."""
    if len(line) != 6 or line[0] != "S":
        return None
    try:
        n = int(line[1:5], 16)
        chk = int(line[5], 16)
    except ValueError:
        return None
    if chk != ((n >> 12) ^ (n >> 8) ^ (n >> 4) ^ n) & 0xF:
        return None  # corrupted in transit
    return n


def open_bluetooth():
    candidates = bluetooth_ports()
    if PORT:
        candidates = [p for p in candidates if p.device.upper() == PORT.upper()]
        if not candidates:
            print(f"{PORT} is not a Bluetooth serial port, so it was refused.")
            print("(This script only uses Bluetooth, never USB.)")
            return None
    if not candidates:
        print("No Bluetooth serial ports found. Pair the HC-05 in Windows Bluetooth "
              "settings first (PIN 1234 or 0000).")
        return None

    for p in candidates:
        print(f"Trying Bluetooth port {p.device} ({p.description})...")
        try:
            s = serial.Serial(p.device, BAUD_RATE, timeout=0.1)
        except serial.SerialException as e:
            print(f"  couldn't open: {e}")
            continue
        deadline = time.monotonic() + PROBE_SECONDS
        while time.monotonic() < deadline:
            line = s.readline().decode("utf-8", errors="ignore").strip()
            if parse_snapshot(line) is not None:
                print(f"  receiving data over Bluetooth on {p.device}")
                return s
        print("  no data from the Arduino on this port")
        s.close()
    return None


ser = open_bluetooth()
if ser is None:
    print("Couldn't establish a Bluetooth link. Check that the HC-05 is powered and paired, "
          "and that the Arduino sketch is running.")
    raise SystemExit
ser.reset_input_buffer()
ser.timeout = 0.005  # short reads keep the loop fast and the timers accurate
print("Connected. Focus Notepad or a game and use the controller.")

# ------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------

# every keyboard key we might touch
all_keys = set(JOY_KEYS.values())
for _kind, _arg in BUTTON_ACTIONS.values():
    if _kind in ("tap", "hold"):
        all_keys.add(_arg)

held = {k: False for k in all_keys}
next_repeat = {k: 0.0 for k in all_keys}
pending_release = {}   # key -> time to release (for taps)


def update_key(key, should_press, now, repeat=True):
    """Hold a key while should_press; optionally auto-repeat like a keyboard."""
    if should_press:
        if not held[key]:
            keyboard.press(key)
            held[key] = True
            next_repeat[key] = now + JOY_REPEAT_DELAY
        elif repeat and now >= next_repeat[key]:
            keyboard.press(key)  # another key-down, like auto-repeat
            next_repeat[key] = now + JOY_REPEAT_INTERVAL
    elif held[key]:
        keyboard.release(key)
        held[key] = False


def tap_key(key, now):
    """Press a key now and release it TAP_DURATION later (no blocking sleep)."""
    keyboard.press(key)
    pending_release[key] = now + TAP_DURATION


def move_mouse(dx, dy):
    user32.mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)


def scroll(notches):
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, (notches * WHEEL_DELTA) & 0xFFFFFFFF, 0)


def mouse_down(button):
    if not mouse_held[button]:
        user32.mouse_event(MOUSE_BUTTON_FLAGS[button][0], 0, 0, 0, 0)
        mouse_held[button] = True


def mouse_up(button):
    if mouse_held[button]:
        user32.mouse_event(MOUSE_BUTTON_FLAGS[button][1], 0, 0, 0, 0)
        mouse_held[button] = False


# ------------------------------------------------------------
# Button logic
# ------------------------------------------------------------
button_down = {name: False for name in BUTTON_ACTIONS}
next_fire = {name: 0.0 for name in BUTTON_ACTIONS}


def on_press(name, now):
    kind, arg = BUTTON_ACTIONS[name]
    if kind == "tap":
        tap_key(arg, now)
        next_fire[name] = now + TAP_HOLD_DELAY
    elif kind == "scroll":
        scroll(arg)
        next_fire[name] = now + TAP_HOLD_DELAY
    elif kind == "hold":
        update_key(arg, True, now, repeat=False)
    elif kind == "click":
        mouse_down(arg)
    elif kind == "move":
        next_fire[name] = now  # first step happens right away


def on_release(name, now):
    kind, arg = BUTTON_ACTIONS[name]
    if kind == "hold":
        update_key(arg, False, now)
    elif kind == "click":
        mouse_up(arg)


def run_repeats(now):
    """Things that happen over time while a button stays held."""
    for name, is_down in button_down.items():
        if not is_down:
            continue
        kind, arg = BUTTON_ACTIONS[name]
        if kind in ("tap", "scroll"):
            if TAP_AUTO_REPEAT and now >= next_fire[name]:
                if kind == "tap":
                    tap_key(arg, now)
                else:
                    scroll(arg)
                next_fire[name] = now + TAP_REPEAT_INTERVAL
        elif kind == "move":
            if now >= next_fire[name]:
                move_mouse(arg[0] * MOUSE_STEP, arg[1] * MOUSE_STEP)
                next_fire[name] += MOUSE_INTERVAL
                if next_fire[name] < now:      # fell behind: don't burst to catch up
                    next_fire[name] = now + MOUSE_INTERVAL


def apply_state(mask, now):
    # pushbuttons / switches: react to changes
    for name in BUTTON_ACTIONS:
        is_down = bool((mask >> BITS[name]) & 1)
        if is_down and not button_down[name]:
            button_down[name] = True
            on_press(name, now)
        elif not is_down and button_down[name]:
            button_down[name] = False
            on_release(name, now)

    # joystick directions -> held keys
    for name, key in JOY_KEYS.items():
        update_key(key, bool((mask >> BITS[name]) & 1), now)


# ------------------------------------------------------------
# Main loop
# ------------------------------------------------------------
rx_buf = bytearray()
cur_state = 0
last_rx = time.monotonic()

try:
    while True:
        data = ser.read(ser.in_waiting or 1)
        if data:
            rx_buf += data
            while b"\n" in rx_buf:
                raw, _, rx_buf = rx_buf.partition(b"\n")
                mask = parse_snapshot(raw.decode("utf-8", errors="ignore").strip())
                if mask is not None:
                    cur_state = mask
                    last_rx = time.monotonic()
            if len(rx_buf) > 64:   # junk without a newline: drop it
                rx_buf.clear()

        now = time.monotonic()

        if now - last_rx > LINK_TIMEOUT:
            cur_state = 0          # link lost: release everything

        apply_state(cur_state, now)
        run_repeats(now)

        for k, t in list(pending_release.items()):
            if now >= t:
                keyboard.release(k)
                del pending_release[k]

except KeyboardInterrupt:
    pass
except serial.SerialException as e:
    print(f"Serial error: {e}")
finally:
    for k in all_keys:
        keyboard.release(k)
    for b in ("left", "right"):
        mouse_up(b)
    ser.close()
    print("Closed. All keys released.")