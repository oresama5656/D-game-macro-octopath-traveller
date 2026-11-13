"""Windows keyboard and client-area capture. Import does not send input."""
import ctypes as C
from ctypes import wintypes as W
from PIL import ImageGrab
import threading
import time

u = C.WinDLL("user32", use_last_error=True)
u.GetForegroundWindow.restype = W.HWND
u.IsWindow.argtypes = [W.HWND]
u.IsIconic.argtypes = [W.HWND]
u.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
u.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
u.PostMessageW.restype = W.BOOL
u.IsWindowVisible.argtypes = [W.HWND]
u.MapVirtualKeyW.argtypes = [W.UINT, W.UINT]
u.GetAsyncKeyState.argtypes = [C.c_int]
u.GetAsyncKeyState.restype = W.SHORT


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class PAYLOAD(C.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _fields_ = [("type", W.DWORD), ("payload", PAYLOAD)]


u.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
u.SendInput.restype = W.UINT
KEYS = {"left": 0x25, "right": 0x27, "up": 0x26, "down": 0x28,
        "lshift": 0xA0, "rshift": 0xA1, "backspace": 0x08,
        "enter": 0x0D, "space": 0x20, **{chr(n).lower(): n for n in range(65, 91)}}


def windows():
    found = []
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

    @callback_type
    def visit(hwnd, unused):
        name = C.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, name, 512)
        if u.IsWindowVisible(hwnd) and name.value.strip().upper() == "OCTOPATH TRAVELER":
            found.append((hwnd, name.value.strip()))
        return True

    u.EnumWindows.argtypes = [callback_type, W.LPARAM]
    u.EnumWindows(visit, 0)
    return found


def foreground(hwnd):
    return bool(u.IsWindow(hwnd) and not u.IsIconic(hwnd) and u.GetForegroundWindow() == hwnd)


def capture(hwnd):
    if not foreground(hwnd):
        raise RuntimeError("ゲームを前面にしてください")
    rect, point = W.RECT(), W.POINT()
    if not u.GetClientRect(hwnd, C.byref(rect)) or not u.ClientToScreen(hwnd, C.byref(point)):
        raise RuntimeError("ゲーム画面の位置を取得できません")
    width, height = rect.right, rect.bottom
    if width < 320 or height < 200:
        raise RuntimeError("ゲーム画面が小さすぎます")
    return ImageGrab.grab((point.x, point.y, point.x + width, point.y + height), all_screens=True).convert("RGB")


def background_available(hwnd):
    return bool(u.IsWindow(hwnd) and not u.IsIconic(hwnd))


def capture_background(hwnd):
    """Render the target HWND, including when another window covers it."""
    if not background_available(hwnd):
        raise RuntimeError("ゲームが閉じられたか最小化されました")
    g = C.WinDLL("gdi32", use_last_error=True)
    u.GetDC.argtypes, u.GetDC.restype = [W.HWND], W.HDC
    u.ReleaseDC.argtypes = [W.HWND, W.HDC]
    u.PrintWindow.argtypes, u.PrintWindow.restype = [W.HWND, W.HDC, W.UINT], W.BOOL
    g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [W.HDC], W.HDC
    g.CreateCompatibleBitmap.argtypes, g.CreateCompatibleBitmap.restype = [W.HDC, C.c_int, C.c_int], W.HBITMAP
    g.SelectObject.argtypes, g.SelectObject.restype = [W.HDC, W.HGDIOBJ], W.HGDIOBJ
    g.DeleteObject.argtypes = [W.HGDIOBJ]
    g.DeleteDC.argtypes = [W.HDC]

    class HEADER(C.Structure):
        _fields_ = [("size", W.DWORD), ("width", W.LONG), ("height", W.LONG), ("planes", W.WORD),
                    ("bits", W.WORD), ("compression", W.DWORD), ("image_size", W.DWORD),
                    ("xppm", W.LONG), ("yppm", W.LONG), ("colors", W.DWORD), ("important", W.DWORD)]

    class INFO(C.Structure):
        _fields_ = [("header", HEADER), ("colors", W.DWORD * 3)]

    g.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, C.c_void_p, C.POINTER(INFO), W.UINT]
    rect, client, point = W.RECT(), W.RECT(), W.POINT()
    if not u.GetWindowRect(hwnd, C.byref(rect)) or not u.GetClientRect(hwnd, C.byref(client)) or not u.ClientToScreen(hwnd, C.byref(point)):
        raise RuntimeError("ゲーム画面の位置を取得できません")
    width, height = rect.right-rect.left, rect.bottom-rect.top
    if width < 320 or height < 200 or width > 16384 or height > 16384:
        raise RuntimeError("ゲーム画面のサイズが不正です")
    dc, memory, bitmap, previous = None, None, None, None
    try:
        dc = u.GetDC(hwnd)
        if not dc:
            raise RuntimeError("ゲームの描画領域を取得できません")
        memory = g.CreateCompatibleDC(dc)
        bitmap = g.CreateCompatibleBitmap(dc, width, height)
        if not memory or not bitmap:
            raise RuntimeError("画像取得用の領域を作成できません")
        previous = g.SelectObject(memory, bitmap)
        if not u.PrintWindow(hwnd, memory, 2):
            raise RuntimeError("ゲームのバックグラウンド画像取得に失敗しました")
        g.SelectObject(memory, previous)
        previous = None
        info = INFO(header=HEADER(C.sizeof(HEADER), width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0))
        buffer = C.create_string_buffer(width*height*4)
        if g.GetDIBits(memory, bitmap, 0, height, buffer, C.byref(info), 0) != height:
            raise RuntimeError("画像の読み出しに失敗しました")
        from PIL import Image
        image = Image.frombytes("RGB", (width, height), buffer.raw, "raw", "BGRX")
        left, top = point.x-rect.left, point.y-rect.top
        return image.crop((left, top, left+client.right, top+client.bottom))
    finally:
        if previous and memory:
            g.SelectObject(memory, previous)
        if bitmap:
            g.DeleteObject(bitmap)
        if memory:
            g.DeleteDC(memory)
        if dc:
            u.ReleaseDC(hwnd, dc)


class BackgroundFrames:
    """Keep blocking PrintWindow calls off the UI and emergency-stop thread."""
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.error = None
        self.sequence = 0
        self.started = time.monotonic()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.closed.is_set():
            try:
                image = capture_background(self.hwnd)
                with self.lock:
                    self.sequence += 1
                    self.latest = (self.sequence, time.monotonic(), image)
            except Exception as error:
                with self.lock:
                    self.error = str(error)
                return
            self.closed.wait(.06)

    def poll(self):
        with self.lock:
            latest, error = self.latest, self.error
        if error:
            raise RuntimeError(error)
        if time.monotonic() - (latest[1] if latest else self.started) > 2:
            raise RuntimeError("ゲーム画面の取得が2秒以上更新されないため停止")
        return (latest[0], latest[2]) if latest else None

    def close(self):
        self.closed.set()


def pressed(vk):
    return bool(u.GetAsyncKeyState(vk) & 0x8000)


class Keyboard:
    def __init__(self):
        self.held = set()

    def send(self, name, down):
        vk = KEYS[name]
        scan = u.MapVirtualKeyW(vk, 0)
        flags = 0x0008 | (0 if down else 0x0002)
        if name in ("left", "right", "up", "down"):
            flags |= 0x0001
        packet = INPUT(type=1, payload=PAYLOAD(ki=KEYBDINPUT(0, scan, flags, 0, 0)))
        if u.SendInput(1, C.byref(packet), C.sizeof(INPUT)) != 1:
            raise RuntimeError("キー送信に失敗しました。ゲームとツールの実行権限を確認してください")
        if down:
            self.held.add(name)
        else:
            self.held.discard(name)

    def hold(self, names):
        names = [names] if isinstance(names, str) else list(dict.fromkeys(names))
        wanted = set(names)
        for held in list(self.held - wanted):
            self.send(held, False)
        for name in names:
            if name not in self.held:
                self.send(name, True)

    def release(self):
        errors = []
        for name in list(self.held):
            try:
                self.send(name, False)
            except RuntimeError as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError(" / ".join(errors))


class WindowKeyboard(Keyboard):
    """Targeted window messages; never falls back to global SendInput."""
    def __init__(self, hwnd):
        super().__init__()
        self.hwnd = hwnd

    def send(self, name, down):
        if not u.IsWindow(self.hwnd):
            if down:
                raise RuntimeError("送信先のゲームが閉じられました")
            self.held.discard(name)
            return
        vk = KEYS[name]
        scan = u.MapVirtualKeyW(vk, 0)
        bits = 1 | (scan << 16)
        if name in ("left", "right", "up", "down"):
            bits |= 1 << 24
        if not down:
            bits |= (1 << 30) | (1 << 31)
        if not u.PostMessageW(self.hwnd, 0x100 if down else 0x101, vk, bits):
            raise RuntimeError("ゲーム宛てのキー通知に失敗しました")
        if down:
            self.held.add(name)
        else:
            self.held.discard(name)
