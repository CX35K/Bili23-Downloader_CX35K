# -*- coding: utf-8 -*-
r"""
回归：内置浏览器播放视频时点右上角 × 能否正常退出（不卡死、对话框可见）

背景：qfluentwidgets 的对话框是"子控件 + 蒙层"（MaskDialogBase），而 WebView2 是原生子窗口，
原生子窗口永远画在 Qt 子控件上面 → 关闭确认框会被网页盖住，看起来像卡死。
修复：有 Qt 蒙层对话框出现时自动隐藏 WebView2
（util/browser/webview2.py::set_visible + gui/interface/browser.py::_check_overlay）。

本测试验证：
  1. 播放视频时触发关闭 → 关闭确认框**可见**（网页已隐藏）；
  2. 选「退出程序」并确认 → 进程能正常退出（退出码 0）；
  3. 全程不卡死（45 秒看门狗，卡住会 dump 所有线程栈）。

运行：
    "D:\Bili23 Downloader\runtime\python.exe" -u tools\test_browser_exit.py
"""

import faulthandler
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")

sys.path.insert(0, SRC)
sys.path.insert(0, ROOT)

import launcher  # noqa: E402

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QTimer, QPoint  # noqa: E402

import main  # noqa: E402

VIDEO_URL = "https://www.bilibili.com/video/BV1GJ411x7h7"

STATE = {"phase": "init", "since": time.time(), "log": []}
DUMP_FILE = os.path.join(ROOT, "browser_exit_hang_trace.txt")


def log(message):
    print("[%6.2fs] %s" % (time.time() - STATE["start"], message), flush = True)
    STATE["log"].append(message)


def dump_and_die():
    with open(DUMP_FILE, "w", encoding = "utf-8") as f:
        f.write("卡死现场：内置浏览器播放视频时退出\n阶段：%s\n\n" % STATE["phase"])
        faulthandler.dump_traceback(file = f, all_threads = True)

    print("\n===== 卡死：线程栈 =====", flush = True)
    faulthandler.dump_traceback(all_threads = True)

    os._exit(3)


def main_test():
    STATE["start"] = time.time()

    app = main.Application(sys.argv)
    app.setup_app()

    from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QRadioButton

    from gui.interface.main_window import MainWindow
    from util.common.config import config
    from util.common.enum import WhenClose

    window = MainWindow()
    app.window = window

    original_when_close = config.get(config.when_close_window)
    config.set(config.when_close_window, WhenClose.ALWAYS_ASK)

    def finish(code, reason):
        config.set(config.when_close_window, original_when_close)

        with open(os.path.join(ROOT, "browser_exit_result.json"), "w", encoding = "utf-8") as f:
            json.dump({"code": code, "reason": reason, "log": STATE["log"]}, f, ensure_ascii = False, indent = 2)

        log("结果：" + reason)
        os._exit(code)

    def find_overlay_dialog():
        # qfluentwidgets 对话框是子控件（不是原生顶层窗口），activeModalWidget 找不到
        for widget in QApplication.allWidgets():
            if isinstance(widget, QDialog) and widget.isVisible() and not widget.isWindow():
                if widget.window() is window:
                    return widget

        return None

    def real_mouse_click_global(global_point):
        """用真实鼠标点击全局坐标（不用 widget.click()，才能测出"原生子窗口吃鼠标"这类问题）"""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error = True)
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        user32.SetCursorPos(int(global_point.x()), int(global_point.y()))
        time.sleep(0.15)
        user32.mouse_event(0x0002, 0, 0, 0, None)
        time.sleep(0.06)
        user32.mouse_event(0x0004, 0, 0, 0, None)

    def pick_exit_and_accept(dialog):
        try:
            for radio in dialog.findChildren(QRadioButton):
                if "退出" in radio.text() or "Exit" in radio.text():
                    radio.click()

            for button in dialog.findChildren(QPushButton):
                if button.text() in ("确认", "OK") and button.isVisible():
                    # mapToGlobal 返回的是逻辑坐标（DIP），SetCursorPos 要物理像素。
                    # 用"左上角 + 自身一半尺寸"算中心，别直接用 rect().center() 传进 mapToGlobal
                    ratio = dialog.devicePixelRatioF()
                    top_left = button.mapToGlobal(QPoint(0, 0))
                    center = QPoint(top_left.x() + button.width() // 2, top_left.y() + button.height() // 2)
                    physical = QPoint(int(center.x() * ratio), int(center.y() * ratio))
                    log("真实鼠标点击「确认」：逻辑(%d,%d) 物理(%d,%d) dpr=%s" % (
                        center.x(), center.y(), physical.x(), physical.y(), ratio))

                    hit = QApplication.widgetAt(center)
                    log("widgetAt(逻辑点) = %r visible=%r" % (
                        hit, hit.isVisible() if hit is not None else None))

                    btn_rect = button.geometry()
                    log("按钮本地 rect=%r 全局左上=%r dialog.isWindow=%r dialog.window=%r" % (
                        btn_rect, button.mapToGlobal(btn_rect.topLeft()), dialog.isWindow(), dialog.window()))

                    # 看看物理点底下到底是哪个 HWND（Windows 层面，不是 Qt 层面）
                    user32 = ctypes.windll.user32
                    user32.WindowFromPoint.restype = wintypes.HWND
                    pt = wintypes.POINT(physical.x(), physical.y())
                    under = user32.WindowFromPoint(pt)
                    cls = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(under, cls, 256)
                    log("物理点底下 HWND=%s class=%r" % (under, cls.value))

                    parent = user32.GetParent(under)
                    depth = 0
                    while parent and depth < 4:
                        cls2 = ctypes.create_unicode_buffer(256)
                        user32.GetClassNameW(parent, cls2, 256)
                        log("   父窗口 HWND=%s class=%r" % (parent, cls2.value))
                        parent = user32.GetParent(parent)
                        depth += 1
                    log("host.isVisible=%r" % (self_host_visible(),))

                    # 把这些原生 HWND 和 Qt 控件对上号
                    widgets = {int(w.winId()): w for w in QApplication.allWidgets()}
                    chain = []
                    h = under
                    while h:
                        chain.append(h)
                        h = user32.GetParent(h)

                    for h in chain:
                        w = widgets.get(int(h))
                        if w is None:
                            log("   HWND=%s -> 无对应 Qt 控件" % h)
                            continue
                        log("   HWND=%s -> %s name=%r visible=%r geom=%r" % (
                            h, type(w).__name__, w.objectName(), w.isVisible(), w.geometry()))

                    # 先只移动光标，确认 OS 光标位置和 Qt 命中是否一致
                    user32.SetCursorPos(physical.x(), physical.y())
                    time.sleep(0.2)
                    pt32 = wintypes.POINT()
                    user32.GetCursorPos(ctypes.byref(pt32))
                    from PySide6.QtGui import QCursor
                    qpos = QCursor.pos()
                    qhit = QApplication.widgetAt(qpos)
                    log("光标实际物理=(%d,%d) QCursor逻辑=(%d,%d) widgetAt=%r" % (
                        pt32.x, pt32.y, qpos.x(), qpos.y(), qhit))

                    # 激活窗口再点（第一次点击常被用来激活窗口而丢掉）
                    fg = user32.GetForegroundWindow()
                    log("前台窗口=%s 主窗口=%s" % (fg, int(window.winId())))
                    user32.SetForegroundWindow(int(window.winId()))
                    time.sleep(0.3)
                    fg2 = user32.GetForegroundWindow()
                    log("激活后前台窗口=%s" % (fg2,))

                    real_mouse_click_global(physical)
                    time.sleep(0.6)
                    real_mouse_click_global(physical)
                    time.sleep(1.2)
                    log("点「确认」后：dialog.isVisible=%r" % dialog.isVisible())

                    if dialog.isVisible():
                        # 再点「取消」，验证鼠标到底能不能到对话框
                        cancel = None
                        for b in dialog.findChildren(QPushButton):
                            if b.text() in ("取消", "Cancel") and b.isVisible():
                                cancel = b

                        if cancel is not None:
                            tl = cancel.mapToGlobal(QPoint(0, 0))
                            ctr = QPoint(tl.x() + cancel.width() // 2, tl.y() + cancel.height() // 2)
                            cphys = QPoint(int(ctr.x() * ratio), int(ctr.y() * ratio))
                            log("改点「取消」：物理(%d,%d)" % (cphys.x(), cphys.y()))
                            real_mouse_click_global(cphys)
                            time.sleep(0.8)
                            log("点「取消」后：dialog.isVisible=%r" % dialog.isVisible())

                    return

            dialog.accept()

        except Exception as e:
            log("操作对话框失败：%r" % (e,))

    def self_host_visible():
        browser = window.browser_interface
        return browser.host.isVisible() if browser is not None else None

    def tick():
        elapsed = time.time() - STATE["start"]
        browser = window.browser_interface

        if elapsed > 120:
            finish(2, "前置条件超时")
            return

        if STATE["phase"] == "init":
            if window.initialized or elapsed > 6:
                log("主窗口就绪")
                window.navigationInterface.items["BrowserInterface"].click()
                STATE["phase"] = "wait_browser"
                STATE["since"] = time.time()

        elif STATE["phase"] == "wait_browser":
            if browser is not None and browser._ready and browser._injected \
                    and "bilibili.com" in (browser._current_url or "") \
                    and time.time() - STATE["since"] > 10:
                log("首页就绪（已注入 cookie）")
                browser.navigate(VIDEO_URL)
                STATE["phase"] = "wait_page"
                STATE["since"] = time.time()

        elif STATE["phase"] == "wait_page":
            if time.time() - STATE["since"] > 6:
                def on_video(value):
                    if value and (value.get("currentTime") or 0) > 0.5:
                        log("视频正在播放，触发关闭窗口")
                        STATE["phase"] = "wait_dialog"
                        STATE["since"] = time.time()
                        threading.Timer(45, dump_and_die).start()
                        QTimer.singleShot(200, window.close)

                browser._bridge.run_js(
                    "(() => { const v = document.querySelector('video');"
                    " if (v) { v.muted = true; v.play().catch(()=>{}); }"
                    " return v ? {currentTime: v.currentTime, readyState: v.readyState} : null; })()",
                    on_video
                )

        elif STATE["phase"] == "wait_dialog":
            dialog = find_overlay_dialog()

            if dialog is None:
                return

            if not STATE.get("dialog_seen"):
                STATE["dialog_seen"] = True
                log("关闭确认框已出现；网页已隐藏=%r 可见=%r" % (browser._overlay_hidden, dialog.isVisible()))

                u = ctypes.windll.user32
                log("GetCapture=%s GetFocus=%s GetForeground=%s" % (
                    u.GetCapture(), u.GetFocus(), u.GetForegroundWindow()))

                # 先试 PostMessage 点击「确认」位置：如果它能关掉弹窗，说明问题在输入队列/鼠标捕获，
                # 而不是 Qt 控件本身
                lx, ly = 831, 654
                user32 = u
                lparam = (ly << 16) | (lx & 0xFFFF)
                user32.PostMessageW(int(window.winId()), 0x0200, 0, lparam)
                user32.PostMessageW(int(window.winId()), 0x0201, 0x0001, lparam)
                user32.PostMessageW(int(window.winId()), 0x0202, 0, lparam)
                time.sleep(0.8)
                log("PostMessage 点「确认」后：dialog.isVisible=%r" % dialog.isVisible())

                if not dialog.isVisible():
                    STATE["dialog_clicked_by_post"] = True
                    return

                try:
                    from PySide6.QtGui import QGuiApplication

                    rect = window.frameGeometry()
                    pix = QGuiApplication.primaryScreen().grabWindow(
                        0, rect.left(), rect.top(), rect.width(), rect.height()
                    )
                    path = os.path.join(ROOT, "docs", "15_exit_dialog_visible.png")
                    pix.save(path, "PNG")
                    log("截图：%s" % path)
                except Exception as e:
                    log("截图失败：%r" % (e,))

                pick_exit_and_accept(dialog)

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(500)

    app.exec()

    finish(0, "app.exec() 正常返回（退出流程完成）")


if __name__ == "__main__":
    main_test()
