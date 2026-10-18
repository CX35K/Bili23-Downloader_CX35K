# -*- coding: utf-8 -*-
"""读取指定进程的 ERROR 弹窗里的文本（PyStand 引导脚本异常时会弹这个）"""
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error = True)

EnumWindows = user32.EnumWindows
EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
EnumChildWindows = user32.EnumChildWindows
EnumChildWindows.argtypes = [wintypes.HWND, ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
GetWindowTextW = user32.GetWindowTextW
GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

TEXT = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def get_text(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(8192)
    GetWindowTextW(hwnd, buf, 8192)
    return buf.value


def main():
    target = int(sys.argv[1])
    found = []

    def on_window(hwnd, _):
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        if pid.value != target:
            return True

        title = get_text(hwnd)

        if title:
            found.append((hwnd, title))

        return True

    EnumWindows(TEXT(on_window), 0)

    print("窗口：", [(hex(h), t) for h, t in found])

    for hwnd, title in found:
        if "ERROR" in title.upper():
            print("\n=== ERROR 弹窗内容 ===")

            def on_child(child, _):
                text = get_text(child)
                if text:
                    print(text)
                return True

            EnumChildWindows(hwnd, TEXT(on_child), 0)


if __name__ == "__main__":
    main()
