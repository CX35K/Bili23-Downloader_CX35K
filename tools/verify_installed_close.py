# -*- coding: utf-8 -*-
r"""
在正式安装版上验证：「浏览器页 → 点 × → 关闭确认框可见 → 确认能退出」

自动做：
  1. 找到 Bili23 Downloader 窗口；
  2. 点导航栏「浏览器」（物理左键消息，DPI 感知）；
  3. 等 WebView2 起来（截图 16）；
  4. 点右上角 ×；
  5. 截图 17，确认关闭确认框出现（网页应被隐藏）；
  6. 发 Enter 确认退出，等进程消失。

用法：
    python tools/verify_installed_close.py [--pid <pid>]
"""

import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOT = os.path.join(ROOT, "docs")

sys.path.append(r"D:\Bili23 Downloader\site-packages")

user32 = ctypes.WinDLL("user32", use_last_error = True)
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]


def post_click(hwnd, x, y):
    lparam = (y << 16) | (x & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0200, 0, lparam)
    user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)
    user32.PostMessageW(hwnd, 0x0202, 0, lparam)


def post_key(hwnd, vk):
    user32.PostMessageW(hwnd, 0x0100, vk, 0x001C0001)
    user32.PostMessageW(hwnd, 0x0101, vk, 0xC01C0001)


def shot(hwnd, name):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])
    pix = app.primaryScreen().grabWindow(0, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    path = os.path.join(SHOT, name)
    pix.save(path, "PNG")
    print("截图：", path, pix.width(), pix.height())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--process", default = "Bili23.exe")
    args = parser.parse_args()

    hwnd = user32.FindWindowW(None, "Bili23 Downloader")

    if not hwnd:
        print("找不到窗口")
        sys.exit(1)

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    print("窗口：hwnd=%s size=%dx%d" % (hwnd, width, height))

    # 1) 点导航栏「浏览器」
    post_click(hwnd, 50, 207)
    print("已点「浏览器」，等 WebView2 …")
    time.sleep(12)

    shot(hwnd, "16_installed_browser_opened.png")

    # 2) 点右上角 ×
    post_click(hwnd, width - 36, 20)
    print("已点 ×，等关闭确认框 …")
    time.sleep(2.5)

    shot(hwnd, "17_installed_exit_dialog.png")

    # 3) Enter 确认「退出程序」
    post_key(hwnd, 0x0D)
    print("已发 Enter，等进程退出 …")

    deadline = time.time() + 15

    while time.time() < deadline:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Bili23.exe", "/NH"],
            capture_output = True, text = True, encoding = "gbk", errors = "replace"
        )

        if "Bili23.exe" not in result.stdout:
            print("✅ 进程已退出")
            return

        time.sleep(1)

    print("❌ 进程仍在运行（卡死/未退出）")
    sys.exit(2)


if __name__ == "__main__":
    main()
