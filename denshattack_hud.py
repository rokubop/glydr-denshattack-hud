"""
Denshattack Glydr pedal -- standalone, cross-platform.

Each F-key from the pedal lights up the overlay and sends its mapped key to
the game.

Watches F2-F24 globally. Set EMIT_KEYS = False for a draw-only overlay.

Runs on Windows, macOS and Linux.

    python denshattack_hud.py

Dependencies:
    Windows  none at all -- stdlib tkinter + ctypes.
    macOS    pip install pynput
             Also grant your terminal Accessibility permission under
             System Settings > Privacy & Security > Accessibility, or no
             keys will be seen.
    Linux    pip install pynput      (X11; Wayland generally blocks global
                                      key capture regardless of toolkit)

Quit with CTRL + SHIFT + Q, or Ctrl+C in the console that launched it.

Feature support is not identical everywhere -- see PLATFORM NOTES at the
bottom of this file. The HUD itself draws the same on all three.
"""

import sys
import tkinter as tk

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MONITOR_INDEX = 0     # 0 = primary. 1 = second monitor, etc.

# Which edge of the monitor to stick to. Horizontal: left, center, right.
# Vertical: top, middle, bottom. e.g. "left_top", "center_middle".
ANCHOR = "right_middle"
OFFSET_X = 16         # inset from the anchored edge, ignored when centered
OFFSET_Y = 0          # nudge down, negative for up

OPACITY = 0.92        # 0.0 - 1.0, whole-window
CLICK_THROUGH = True  # mouse clicks pass through to the game (Windows only)

# Send the mapped keys to the focused window. Turn off for a draw-only
# overlay, e.g. if something else is already handling these F-keys.
EMIT_KEYS = True

# Use pynput even on Windows. Only worth setting if the native backend
# misbehaves; the native one needs no install.
FORCE_PYNPUT = False

# First family that's actually installed wins. Nothing exotic here on
# purpose. tkinter falls back silently to something arbitrary if a family is
# missing, so we resolve against the real font list at startup instead.
FONT_CANDIDATES = ("Segoe UI", "Roboto", "Helvetica Neue", "DejaVu Sans",
                   "Verdana", "Arial")
FONT = "TkDefaultFont"  # replaced by resolve_font() once Tk is up

# Colors. tkinter has no per-widget alpha, so these are solid and OPACITY
# above carries the translucency.
UI_BG = "#4A4A4A"
TILE_BG = "#5A5A5A"
BORDER = "#000000"
HIGHLIGHT = "#FFFF00"
HIGHLIGHT_FG = "#000000"
LABEL_FG = "#C8C0D0"
TEXT_FG = "#FFFFFF"
TRANSPARENT_KEY = "#010203"  # any color you'll never draw with

POLL_MS = 8

# F-key -> (keys it outputs, pedal sections it lights up)
# Matches the Glydr configurator grid. Full table in the README.
PEDAL_MAP = {
    "f2":  (["r"],             ["left_flap", "left_heel", "right_toe"]),
    "f3":  (["escape"],        ["left_flap", "left_toe", "right_heel"]),
    "f4":  (["e"],             ["left_flap", "left_toe", "right_toe"]),
    "f5":  (["space"],         ["left_flap"]),
    "f6":  (["ctrl"],          ["left_flap", "left_heel", "right_heel"]),
    "f7":  (["up"],            ["right_flap", "right_toe"]),
    "f8":  (["right", "down"], ["right_flap", "left_toe", "right_heel"]),
    "f9":  (["right", "up"],   ["right_flap", "left_toe", "right_toe"]),
    "f10": (["right"],         ["right_flap", "left_toe"]),
    "f13": (["left", "up"],    ["right_flap", "left_heel", "right_toe"]),
    "f14": (["left"],          ["right_flap", "left_heel"]),
    "f15": (["down"],          ["right_flap", "right_heel"]),
    "f16": (["left", "down"],  ["right_flap", "left_heel", "right_heel"]),
    "f17": (["d", "w"],        ["left_toe", "right_toe"]),
    "f18": (["d"],             ["left_toe"]),
    "f19": (["w"],             ["right_toe"]),
    "f20": (["d", "s"],        ["left_toe", "right_heel"]),
    "f21": (["a", "w"],        ["left_heel", "right_toe"]),
    "f22": (["a"],             ["left_heel"]),
    "f23": (["s"],             ["right_heel"]),
    "f24": (["a", "s"],        ["left_heel", "right_heel"]),
}

# ---------------------------------------------------------------------------
# Which tile does an output key light up
# ---------------------------------------------------------------------------

WASD_KEYS = {"w": "up", "a": "left", "s": "down", "d": "right"}
ARROW_KEYS = {"up": "up", "down": "down", "left": "left", "right": "right"}
ACTION_KEYS = ("space", "e", "ctrl", "q", "r", "x", "escape")


def tile_id(key):
    if key in WASD_KEYS:
        return "wasd_" + WASD_KEYS[key]
    if key in ARROW_KEYS:
        return "arrow_" + ARROW_KEYS[key]
    if key in ACTION_KEYS:
        return "action_" + key
    return None


# ---------------------------------------------------------------------------
# Key watchers -- each exposes .pressed(), a set of names like {"f5", "ctrl"}
# ---------------------------------------------------------------------------

WATCHED = set(PEDAL_MAP) | {"ctrl", "shift", "q"}


class Win32Watcher:
    """Polls GetAsyncKeyState. No dependencies, no hook, no admin."""

    name = "win32"

    def __init__(self):
        import ctypes

        self.user32 = ctypes.windll.user32
        self.vk = {"ctrl": 0x11, "shift": 0x10, "q": 0x51}
        for i in range(1, 25):
            self.vk["f%d" % i] = 0x6F + i

    def start(self):
        pass

    def stop(self):
        pass

    def pressed(self):
        down = self.user32.GetAsyncKeyState
        return {n for n in WATCHED if down(self.vk[n]) & 0x8000}


class PynputWatcher:
    """Event-driven listener. Works on Windows, macOS and X11."""

    name = "pynput"

    def __init__(self):
        from pynput import keyboard

        self.keyboard = keyboard
        self._down = set()
        self._listener = None

    @staticmethod
    def _norm(key):
        name = getattr(key, "name", None)
        if name:
            if name.startswith("ctrl"):
                return "ctrl"
            if name.startswith("shift"):
                return "shift"
            return name
        char = getattr(key, "char", None)
        return char.lower() if char else None

    def start(self):
        def on_press(key):
            n = self._norm(key)
            if n in WATCHED:
                self._down.add(n)

        def on_release(key):
            self._down.discard(self._norm(key))

        self._listener = self.keyboard.Listener(
            on_press=on_press, on_release=on_release)
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()

    def pressed(self):
        return set(self._down)


def make_watcher():
    if IS_WIN and not FORCE_PYNPUT:
        return Win32Watcher()
    try:
        return PynputWatcher()
    except ImportError:
        sys.exit(
            "This platform needs pynput for global key capture.\n"
            "    pip install pynput\n"
            + ("\nmacOS also needs Accessibility permission for your terminal:\n"
               "    System Settings > Privacy & Security > Accessibility\n"
               if IS_MAC else "")
        )


# ---------------------------------------------------------------------------
# Key emitters (only used when EMIT_KEYS is on)
# ---------------------------------------------------------------------------

class Win32Emitter:
    """Scancode injection via SendInput -- what DirectInput games expect."""

    SCAN = {
        "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20,
        "e": 0x12, "q": 0x10, "r": 0x13, "x": 0x2D,
        "space": 0x39, "ctrl": 0x1D, "escape": 0x01,
        "up": 0x48, "left": 0x4B, "right": 0x4D, "down": 0x50,
    }
    EXTENDED = {"up", "left", "right", "down"}

    def __init__(self):
        import ctypes
        import ctypes.wintypes as wt

        self.ctypes = ctypes
        self.user32 = ctypes.windll.user32

        ULONG_PTR = ctypes.POINTER(wt.ULONG)

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD),
                        ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                        ("dwExtraInfo", ULONG_PTR)]

        # The union has to be as wide as its largest member, which is
        # MOUSEINPUT, not KEYBDINPUT. Get this wrong and SendInput rejects
        # every call with a size mismatch and returns 0, silently.
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wt.LONG), ("dy", wt.LONG),
                        ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                        ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class _UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wt.DWORD), ("u", _UNION)]

        self.KEYBDINPUT, self._UNION, self.INPUT = KEYBDINPUT, _UNION, INPUT
        self._warned = False

    def send(self, name, down):
        scan = self.SCAN.get(name)
        if scan is None:
            return
        flags = 0x0008  # KEYEVENTF_SCANCODE
        if name in self.EXTENDED:
            flags |= 0x0001  # KEYEVENTF_EXTENDEDKEY
        if not down:
            flags |= 0x0002  # KEYEVENTF_KEYUP
        inp = self.INPUT(
            type=1,
            u=self._UNION(ki=self.KEYBDINPUT(0, scan, flags, 0, None)),
        )
        sent = self.user32.SendInput(1, self.ctypes.byref(inp),
                                     self.ctypes.sizeof(self.INPUT))
        if not sent and not self._warned:
            self._warned = True
            print("SendInput rejected a key (error %d). Keys are not "
                  "reaching the game." % self.ctypes.get_last_error())


class PynputEmitter:
    def __init__(self):
        from pynput.keyboard import Controller, Key

        self.controller = Controller()
        self.special = {
            "space": Key.space, "ctrl": Key.ctrl, "escape": Key.esc,
            "up": Key.up, "down": Key.down, "left": Key.left,
            "right": Key.right,
        }

    def send(self, name, down):
        key = self.special.get(name, name)
        (self.controller.press if down else self.controller.release)(key)


def make_emitter():
    if IS_WIN and not FORCE_PYNPUT:
        return Win32Emitter()
    return PynputEmitter()


# ---------------------------------------------------------------------------
# Window: transparency, click-through, monitor placement
# ---------------------------------------------------------------------------

def apply_transparency(win):
    """Set up window translucency. Returns the color the canvas should use
    as its background."""
    try:
        win.attributes("-alpha", OPACITY)
    except tk.TclError:
        pass

    if IS_WIN:
        win.attributes("-transparentcolor", TRANSPARENT_KEY)
        win.configure(bg=TRANSPARENT_KEY)
        return TRANSPARENT_KEY

    if IS_MAC:
        try:
            win.attributes("-transparent", True)
            win.configure(bg="systemTransparent")
            return "systemTransparent"
        except tk.TclError:
            pass

    # Linux, or macOS without transparent-window support: no color keying,
    # so the window is an opaque rounded-less rectangle in the panel color.
    win.configure(bg=UI_BG)
    return UI_BG


def apply_click_through(win):
    """True if clicks now pass through to whatever is underneath."""
    if not CLICK_THROUGH:
        return False
    if not IS_WIN:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    GWL_EXSTYLE = -20
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= 0x00080000  # WS_EX_LAYERED
    style |= 0x08000000  # WS_EX_NOACTIVATE  -- never steal game focus
    style |= 0x00000080  # WS_EX_TOOLWINDOW  -- keep out of alt-tab
    style |= 0x00000020  # WS_EX_TRANSPARENT -- clicks fall through
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    return True


def monitor_rect(win, index):
    """(x, y, w, h) of the requested monitor, primary first."""
    if IS_WIN:
        import ctypes
        import ctypes.wintypes as wt

        rects = []
        PROC = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HMONITOR, wt.HDC,
                                  ctypes.POINTER(wt.RECT), wt.LPARAM)

        def cb(hmon, hdc, lprect, lparam):
            r = lprect.contents
            rects.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return 1

        ctypes.windll.user32.EnumDisplayMonitors(0, None, PROC(cb), 0)
        # Enumeration order isn't guaranteed; put the primary (0,0) first.
        rects.sort(key=lambda r: ((r[0], r[1]) != (0, 0), r[0], r[1]))
        if rects:
            return rects[min(index, len(rects) - 1)]
    else:
        try:
            from screeninfo import get_monitors

            mons = sorted(get_monitors(), key=lambda m: not m.is_primary)
            if mons:
                m = mons[min(index, len(mons) - 1)]
                return (m.x, m.y, m.width, m.height)
        except Exception:
            pass

        if index:
            print("MONITOR_INDEX needs `pip install screeninfo` on this "
                  "platform; using the primary display.")

    return (0, 0, win.winfo_screenwidth(), win.winfo_screenheight())


def place(win, w, h):
    """Top-left (x, y) to put a w by h window at, per ANCHOR."""
    mx, my, mw, mh = monitor_rect(win, MONITOR_INDEX)
    horizontal, _, vertical = ANCHOR.partition("_")

    if horizontal == "right":
        x = mx + mw - w - OFFSET_X
    elif horizontal == "center":
        x = mx + (mw - w) // 2
    else:
        x = mx + OFFSET_X

    if vertical == "bottom":
        y = my + mh - h - OFFSET_Y
    elif vertical == "middle":
        y = my + (mh - h) // 2 + OFFSET_Y
    else:
        y = my + OFFSET_Y

    return x, y


def resolve_font():
    """Pick the first installed family from FONT_CANDIDATES.

    Requires an existing Tk root. Falls back to Tk's own default font, which
    is always present, so a machine with none of the candidates still renders.
    """
    global FONT
    import tkinter.font as tkfont

    installed = {name.lower() for name in tkfont.families()}
    for family in FONT_CANDIDATES:
        if family.lower() in installed:
            FONT = family
            return FONT
    FONT = tkfont.nametofont("TkDefaultFont").actual("family")
    return FONT


# ---------------------------------------------------------------------------
# Tiny box-layout engine (the flexbox subset the original layout used)
# ---------------------------------------------------------------------------

class Node:
    def __init__(self, direction="row", gap=0, padding=0, align="start",
                 w=None, h=None, bg=None, border=0, radius=0, hid=None,
                 text=None, size=14, color=None, bold=False, arrow=None,
                 outline=True, children=()):
        self.direction, self.gap, self.padding, self.align = direction, gap, padding, align
        self.w, self.h = w, h
        self.bg, self.border, self.radius = bg, border, radius
        self.hid = hid
        self.text, self.size, self.color, self.bold = text, size, color, bold
        self.arrow, self.outline = arrow, outline
        self.children = list(children)
        self.x = self.y = 0
        self.rect_item = None
        self.fg_items = []
        self.outline_items = []


def measure(n):
    for c in n.children:
        measure(c)
    if n.children:
        g = n.gap * (len(n.children) - 1)
        if n.direction == "row":
            cw = sum(c.w for c in n.children) + g
            ch = max(c.h for c in n.children)
        else:
            cw = max(c.w for c in n.children)
            ch = sum(c.h for c in n.children) + g
        if n.w is None:
            n.w = cw + n.padding * 2
        if n.h is None:
            n.h = ch + n.padding * 2
    else:
        if n.w is None:
            n.w = int(len(n.text or "") * n.size * 0.62)
        if n.h is None:
            n.h = int(n.size * 1.45)


def position(n, x, y):
    n.x, n.y = x, y
    p = n.padding
    cx, cy = x + p, y + p
    inner_w, inner_h = n.w - p * 2, n.h - p * 2
    for c in n.children:
        if n.direction == "row":
            off = (inner_h - c.h) // 2 if n.align == "center" else 0
            position(c, cx, cy + off)
            cx += c.w + n.gap
        else:
            off = (inner_w - c.w) // 2 if n.align == "center" else 0
            position(c, cx + off, cy)
            cy += c.h + n.gap


def walk(n):
    yield n
    for c in n.children:
        yield from walk(c)


# ---------------------------------------------------------------------------
# Painting
# ---------------------------------------------------------------------------

def round_rect(cv, x, y, w, h, r, **kw):
    if r <= 0:
        return cv.create_rectangle(x, y, x + w, y + h, **kw)
    pts = [
        x + r, y, x + w - r, y, x + w, y, x + w, y + r,
        x + w, y + h - r, x + w, y + h, x + w - r, y + h,
        x + r, y + h, x, y + h, x, y + h - r,
        x, y + r, x, y,
    ]
    return cv.create_polygon(pts, smooth=True, **kw)


OUTLINE_OFFSETS = [(-1, -1), (0, -1), (1, -1), (-1, 0),
                   (1, 0), (-1, 1), (0, 1), (1, 1)]

ARROW_POINTS = {
    "up":    [(0.5, 0.18), (0.86, 0.72), (0.14, 0.72)],
    "down":  [(0.5, 0.82), (0.14, 0.28), (0.86, 0.28)],
    "left":  [(0.18, 0.5), (0.72, 0.14), (0.72, 0.86)],
    "right": [(0.82, 0.5), (0.28, 0.14), (0.28, 0.86)],
}


def paint(cv, n):
    if n.bg or n.border:
        n.rect_item = round_rect(
            cv, n.x, n.y, n.w, n.h, n.radius,
            fill=n.bg or "",
            outline=BORDER if n.border else "",
            width=n.border,
        )
    if n.arrow:
        pts = []
        for fx, fy in ARROW_POINTS[n.arrow]:
            pts += [n.x + fx * n.w, n.y + fy * n.h]
        n.fg_items.append(
            cv.create_polygon(pts, fill=TEXT_FG, outline=BORDER, width=2))
    elif n.text:
        font = (FONT, n.size, "bold") if n.bold else (FONT, n.size)
        tx, ty = n.x + n.w / 2, n.y + n.h / 2
        anchor = "center"
        if n.color == LABEL_FG:  # panel captions are left-aligned
            tx, anchor = n.x, "w"
        if n.outline:
            for dx, dy in OUTLINE_OFFSETS:
                n.outline_items.append(cv.create_text(
                    tx + dx, ty + dy, text=n.text, font=font,
                    fill=BORDER, anchor=anchor))
        n.fg_items.append(cv.create_text(
            tx, ty, text=n.text, font=font,
            fill=n.color or TEXT_FG, anchor=anchor))
    for c in n.children:
        paint(cv, c)


def set_highlight(cv, n, on):
    if n.rect_item is not None:
        cv.itemconfig(n.rect_item, fill=HIGHLIGHT if on else (n.bg or ""))
    for item in n.fg_items:
        if n.arrow:
            cv.itemconfig(item, fill=HIGHLIGHT_FG if on else TEXT_FG)
        else:
            cv.itemconfig(item, fill=HIGHLIGHT_FG if on else (n.color or TEXT_FG))
    # a black outline behind black text is a blob -- hide it while lit
    for item in n.outline_items:
        cv.itemconfig(item, state="hidden" if on else "normal")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def key_tile(hid, label, w=40):
    return Node(w=w, h=40, bg=TILE_BG, border=1, hid=hid,
                children=[Node(text=label, size=15, w=w, h=40)])


def arrow_tile(hid, direction):
    return Node(w=40, h=40, bg=TILE_BG, border=1, hid=hid, align="center",
                padding=8, children=[Node(arrow=direction, w=24, h=24)])


def cluster(top, bottom_row):
    return Node(direction="column", gap=2, align="center", padding=8,
                children=[top, Node(direction="row", gap=2, children=bottom_row)])


def caption(text):
    return Node(text=text, size=10, bold=True, color=LABEL_FG, outline=False, h=16)


def panel(title, body):
    return Node(direction="column", gap=6, padding=8, children=[caption(title), body])


def foot_pedal():
    OUTER_W, FLAP_W, SECTION_H, GAP = 70, 44, 48, 2

    def section(hid, w, h):
        return Node(w=w, h=h, bg=TILE_BG, border=1, hid=hid)

    def unit(side, flap_first):
        stack = Node(direction="column", gap=GAP, children=[
            section("%s_toe" % side, OUTER_W, SECTION_H),
            section("%s_heel" % side, OUTER_W, SECTION_H),
        ])
        flap = section("%s_flap" % side, FLAP_W, SECTION_H * 2 + GAP)
        kids = [flap, stack] if flap_first else [stack, flap]
        return Node(direction="row", gap=GAP, children=kids)

    return Node(direction="row", gap=10, padding=8, bg=TILE_BG, border=2,
                radius=8, children=[unit("left", False), unit("right", True)])


def build():
    wasd = cluster(
        key_tile("wasd_up", "W"),
        [key_tile("wasd_left", "A"), key_tile("wasd_down", "S"),
         key_tile("wasd_right", "D")],
    )
    arrows = cluster(
        arrow_tile("arrow_up", "up"),
        [arrow_tile("arrow_left", "left"), arrow_tile("arrow_down", "down"),
         arrow_tile("arrow_right", "right")],
    )
    action_keys = Node(direction="column", gap=6, padding=8, children=[
        Node(direction="row", gap=6, children=[
            key_tile("action_space", "SPACE", 112),
            key_tile("action_e", "E", 44),
            key_tile("action_ctrl", "CTRL", 64),
            key_tile("action_q", "Q", 44),
        ]),
        Node(direction="row", gap=6, children=[
            key_tile("action_r", "R", 44),
            key_tile("action_x", "X", 44),
            key_tile("action_escape", "ESC", 64),
        ]),
    ])

    controls = Node(direction="column", gap=10, children=[
        Node(direction="row", gap=10, children=[wasd, arrows]),
        action_keys,
    ])

    return Node(direction="column", gap=10, padding=10, bg=UI_BG, border=2,
                radius=12, children=[
                    panel("CONTROLS", controls),
                    panel("GLYDR", foot_pedal()),
                ])


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def main():
    root = build()
    measure(root)
    position(root, 0, 0)
    by_id = {n.hid: n for n in walk(root) if n.hid}

    watcher = make_watcher()
    emitter = make_emitter() if EMIT_KEYS else None

    win = tk.Tk()
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    canvas_bg = apply_transparency(win)

    x, y = place(win, root.w, root.h)
    win.geometry("%dx%d+%d+%d" % (root.w, root.h, x, y))

    resolve_font()

    cv = tk.Canvas(win, width=root.w, height=root.h, bg=canvas_bg,
                   highlightthickness=0, bd=0)
    cv.pack()
    paint(cv, root)

    win.update_idletasks()
    through = apply_click_through(win)

    watcher.start()

    lit = set()      # tile/pedal ids currently highlighted
    emitted = set()  # output keys currently held down

    def shutdown():
        if emitter:
            for k in emitted:
                emitter.send(k, False)
        watcher.stop()
        win.destroy()

    def tick():
        nonlocal lit, emitted

        down = watcher.pressed()
        if {"ctrl", "shift", "q"} <= down:
            shutdown()
            return

        want, want_keys = set(), set()
        for f in down & PEDAL_MAP.keys():
            out_keys, sections = PEDAL_MAP[f]
            want.update(sections)
            for k in out_keys:
                want_keys.add(k)
                tid = tile_id(k)
                if tid:
                    want.add(tid)

        for hid in want - lit:
            if hid in by_id:
                set_highlight(cv, by_id[hid], True)
        for hid in lit - want:
            if hid in by_id:
                set_highlight(cv, by_id[hid], False)
        lit = want

        if emitter:
            for k in want_keys - emitted:
                emitter.send(k, True)
            for k in emitted - want_keys:
                emitter.send(k, False)
            emitted = want_keys

        win.after(POLL_MS, tick)

    print("Denshattack Glydr pedal running.  input=%s  font=%s"
          % (watcher.name, FONT))
    print("CTRL+SHIFT+Q to quit.")
    if not EMIT_KEYS:
        print("EMIT_KEYS is off -- drawing only, no keys sent to the game.")
    if CLICK_THROUGH and not through:
        print("Note: click-through is Windows-only. The panel will catch "
              "mouse clicks on this platform -- keep it out of the way.")

    win.after(POLL_MS, tick)
    try:
        win.mainloop()
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# PLATFORM NOTES
#
#                       Windows        macOS              Linux (X11)
#   dependencies        none           pynput             pynput
#   global key capture  native poll    pynput listener    pynput listener
#   transparency        color-keyed    -transparent       whole-window alpha
#   click-through       yes            no                 no
#   MONITOR_INDEX       native         screeninfo         screeninfo
#   key emission        SendInput      pynput Controller  pynput Controller
#
# macOS needs Accessibility permission granted to whatever runs Python, both
# to read keys and to emit them. Without it the HUD draws but never lights up.
#
# Linux under Wayland generally refuses global key capture to unprivileged
# clients; X11 sessions are fine. This is a compositor policy, not a tkinter
# or pynput limitation.
#
# F21-F24 are not reachable on every platform -- pynput exposes f1-f20 on
# macOS and X11. Glydr pedals that emit in that range will light up on
# Windows but not elsewhere; remap them lower in the pedal's own config if
# that matters.
# ---------------------------------------------------------------------------
