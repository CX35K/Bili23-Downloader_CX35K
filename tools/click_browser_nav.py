# -*- coding: utf-8 -*-
"""在已安装的 Bili23 窗口里点击导航栏「浏览器」，验证部署后的完整链路。

坐标坑：本进程默认是 DPI-unaware，Windows 会虚拟化窗口矩形与屏幕坐标，
150% 缩放下算出来的点会偏。这里先把进程设成 Per-Monitor Aware V2，
再用 PostMessage 往窗口客户区（物理像素）发鼠标消息。

用法：
    python tools/click_browser_nav.py [--title "Bili23 Downloader"] [--x 78] [--y 310]
"""

import argparse
import ctypes
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error = True)

try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except Exception:
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default = "Bili23 Downloader")
    parser.add_argument("--x", type = int, default = 78, help = "客户区物理像素 X")
    parser.add_argument("--y", type = int, default = 310, help = "客户区物理像素 Y")
    parser.add_argument("--child", default = "", help = "点击前先激活的子窗口（可选）")
    args = parser.parse_args()

    hwnd = user32.FindWindowW(None, args.title)

    if not hwnd:
        print("找不到窗口")
        sys.exit(1)

    print("hwnd =", hwnd, "点击客户区物理坐标：", args.x, args.y)

    lparam = (args.y << 16) | (args.x & 0xFFFF)

    user32.PostMessageW(hwnd, 0x0200, 0, lparam)  # WM_MOUSEMOVE
    time.sleep(0.1)
    user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)  # WM_LBUTTONDOWN
    time.sleep(0.08)
    user32.PostMessageW(hwnd, 0x0202, 0, lparam)  # WM_LBUTTONUP

    print("已发送点击消息")


if __name__ == "__main__":
    main()
