# -*- coding: utf-8 -*-
r"""
回归：打开过浏览器页后，在「解析」页打开并关闭「关于」对话框，页面不能重叠

场景（用户报的 bug）：
  1. 打开浏览器页，加载 B 站；
  2. 切到「解析」页；
  3. 打开「关于」对话框（fluent 蒙层对话框）；
  4. 关掉它；
  5. 断言：当前页仍是解析页、浏览器页不可见、解析页可见（不能重叠）；
  6. 再切回浏览器页，页面应正常恢复（可见 + URL 还在）。

运行：
    "D:\Bili23 Downloader\runtime\python.exe" -u tools\test_browser_overlap.py
"""

import faulthandler
import json
import os
import threading
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")

sys.path.insert(0, SRC)
sys.path.insert(0, ROOT)

import launcher  # noqa: E402

from PySide6.QtCore import QTimer  # noqa: E402

import main  # noqa: E402

STATE = {"start": time.time(), "phase": "init"}
RESULT = {"ok": False, "checks": []}


def log(message):
    print("[%6.2fs] %s" % (time.time() - STATE["start"], message), flush = True)


def check(name, ok, detail = ""):
    RESULT["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    log(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + str(detail)) if detail and not ok else ""))


def main_test():
    STATE["start"] = time.time()

    app = main.Application(sys.argv)
    app.setup_app()

    from PySide6.QtWidgets import QApplication, QDialog
    from PySide6.QtGui import QGuiApplication

    from gui.interface.main_window import MainWindow

    window = MainWindow()
    app.window = window

    def screenshot(name):
        rect = window.frameGeometry()
        pix = QGuiApplication.primaryScreen().grabWindow(0, rect.left(), rect.top(), rect.width(), rect.height())
        path = os.path.join(ROOT, "docs", name)
        pix.save(path, "PNG")
        log("截图：%s" % path)

    def find_about_dialog():
        for w in QApplication.allWidgets():
            if isinstance(w, QDialog) and w.isVisible() and w.isModal() and w is not window:
                if w.window() is window or w.parent() is window:
                    return w
        return None

    def finish():
        RESULT["ok"] = all(c["ok"] for c in RESULT["checks"])

        with open(os.path.join(ROOT, "browser_overlap_result.json"), "w", encoding = "utf-8") as f:
            json.dump(RESULT, f, ensure_ascii = False, indent = 2)

        log("结果：%r" % RESULT["ok"])
        os._exit(0 if RESULT["ok"] else 3)

    def open_about():
        log("点「关于」")
        # 用队列方式触发，模拟真实点击（不在定时器回调里直接 exec，避免测试假死）
        QTimer.singleShot(0, lambda: window.navigationInterface.items["about"].click())

    def close_about():
        dialog = find_about_dialog()

        if dialog is None:
            log("没找到关于对话框（可能已关闭）")
            return

        log("关闭关于对话框：%r" % (dialog,))
        dialog.reject()

    def tick():
        elapsed = time.time() - STATE["start"]
        browser = window.browser_interface

        if elapsed > 120:
            check("总超时", False)
            finish()
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
                    and time.time() - STATE["since"] > 8:
                log("浏览器页就绪：%s" % browser._current_url)

                # 切到解析页
                window.navigationInterface.items["ParseInterface"].click()
                STATE["phase"] = "about"
                STATE["since"] = time.time()

        elif STATE["phase"] == "about":
            if time.time() - STATE["since"] > 1.5:
                check("已切回解析页", window.stackedWidget.currentWidget() is window.parse_interface)
                open_about()
                STATE["phase"] = "about_open"
                STATE["since"] = time.time()

        elif STATE["phase"] == "about_open":
            if time.time() - STATE["since"] > 2:
                check("关于对话框已打开", find_about_dialog() is not None)
                close_about()
                STATE["phase"] = "after_close"
                STATE["since"] = time.time()

        elif STATE["phase"] == "after_close":
            if time.time() - STATE["since"] > 2:
                current = window.stackedWidget.currentWidget()

                check("当前页仍是解析页", current is window.parse_interface, type(current).__name__)
                check("浏览器页不可见（不重叠）", not browser.isVisible())
                check("解析页可见", window.parse_interface.isVisible())

                screenshot("41_after_about_close.png")

                # 再切回浏览器页，确认能恢复
                window.navigationInterface.items["BrowserInterface"].click()
                STATE["phase"] = "back"
                STATE["since"] = time.time()

        elif STATE["phase"] == "back":
            if time.time() - STATE["since"] > 3:
                def on_state(value):
                    check("切回浏览器页后页面恢复", bool(value) and "bilibili" in (value.get("url") or ""), value)
                    screenshot("42_back_to_browser.png")
                    finish()

                browser._bridge.run_js("({url: location.href, title: document.title})", on_state)
                STATE["phase"] = "done"

    def dump():
        with open(os.path.join(ROOT, "overlap_hang.txt"), "w", encoding="utf-8") as f:
            f.write("阶段：%s\n" % STATE["phase"])
            faulthandler.dump_traceback(file=f, all_threads=True)

        print("\n===== 卡住现场 =====", flush=True)
        faulthandler.dump_traceback(all_threads=True)
        os._exit(4)

    threading.Timer(60, dump).start()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(500)

    app.exec()


if __name__ == "__main__":
    main_test()
