"""Manual feasibility probe: one menu key to the game, without foreground activation."""
import ctypes as C
from ctypes import wintypes as W
import tkinter as tk
from tkinter import ttk
from win32_io import u, windows, foreground, capture_background

u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
u.PostMessageW.restype = W.BOOL


def main():
    root = tk.Tk()
    root.title("Octopath バックグラウンド入力診断")
    root.geometry("510x220+700+500")
    status = tk.StringVar(value="ゲームのメニューで試験。ゲームをアクティブにはしません。")
    ttk.Label(root, textvariable=status, wraplength=480).pack(padx=12, pady=16)

    def send():
        matches = windows()
        if len(matches) != 1:
            status.set("ゲームが一意ではありません")
            return
        hwnd = matches[0][0]
        if foreground(hwnd):
            status.set("ゲームが前面のため中止")
            return
        vk = 0x28
        scan = u.MapVirtualKeyW(vk, 0)
        bits = 1 | (scan << 16) | (1 << 24)
        ok = u.PostMessageW(hwnd, 0x100, vk, bits)

        def release():
            released = u.PostMessageW(hwnd, 0x101, vk, bits | (1 << 30) | (1 << 31))
            status.set(f"通知の受付：down={bool(ok)} up={bool(released)} / ゲームが前面：{foreground(hwnd)}")
        root.after(100, release)

    ttk.Button(root, text="ゲームだけに↓を1回通知（メニュー選択の試験）", command=send).pack(pady=5)
    def screenshot():
        try:
            matches = windows()
            if len(matches) != 1:
                raise RuntimeError("ゲームが一意ではありません")
            image = capture_background(matches[0][0])
            image.save("profiles/background_capture_probe.png")
            status.set(f"ウィンドウ画像を保存しました：{image.size}")
        except Exception as error:
            status.set(str(error))
    ttk.Button(root, text="隠れたゲーム画面の画像取得を試験", command=screenshot).pack(pady=5)
    root.mainloop()


if __name__ == "__main__":
    main()
