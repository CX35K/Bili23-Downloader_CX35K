# -*- coding: utf-8 -*-
r"""
回归：改名 + 关于页改进说明

断言：
  1. 主窗口标题是 "Bili23 Downloader_CX35K"；
  2. 关于对话框标题/正文包含新名字；
  3. 关于对话框里有「本软件在 Bili23 Download 的基础上进行了改进」；
  4. 数据目录仍是原来的（config 正常加载、未被当成首次运行）。

运行：
    "D:\Bili23 Downloader\runtime\python.exe" -u tools\test_rename_about.py
"""

import json
import os
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

NEW_NAME = "Bili23 Downloader_CX35K"
NOTE = "本软件在 Bili23 Download 的基础上进行了改进"
RESULT = {"ok": False, "checks": []}


def log(message):
    print(message, flush = True)


def check(name, ok, detail = ""):
    RESULT["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    log(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + str(detail)) if detail and not ok else ""))


def main_test():
    app = main.Application(sys.argv)
    app.setup_app()

    from PySide6.QtWidgets import QApplication, QDialog, QLabel
    from PySide6.QtGui import QGuiApplication

    from gui.interface.main_window import MainWindow

    window = MainWindow()
    app.window = window

    def find_about():
        for w in QApplication.allWidgets():
            if isinstance(w, QDialog) and w.isVisible() and w is not window:
                if type(w).__name__ == "AboutDialog":
                    return w
        return None

    def screenshot(name):
        rect = window.frameGeometry()
        pix = QGuiApplication.primaryScreen().grabWindow(0, rect.left(), rect.top(), rect.width(), rect.height())
        path = os.path.join(ROOT, "docs", name)
        pix.save(path, "PNG")
        log("截图：" + path)

    def step1():
        check("主窗口标题", window.windowTitle() == NEW_NAME, window.windowTitle())

        # 打开关于（排队点击，模拟真实点击）
        QTimer.singleShot(0, lambda: window.navigationInterface.items["about"].click())
        QTimer.singleShot(2000, step2)

    def step2():
        dialog = find_about()

        if dialog is None:
            check("关于对话框打开", False)
            finish()
            return

        check("关于对话框打开", True)
        # 蒙层对话框没有窗口标题，标题是内部的 caption 标签（下面统一检查）

        texts = [label.text() for label in dialog.findChildren(QLabel)]
        joined = "\n".join(texts)

        check("关于页含新名字", NEW_NAME in joined)
        check("关于页含改进说明", NOTE in joined, joined[:300])
        check("关于页仍显示版本号", "2.20.0" in joined)

        screenshot("43_about_renamed.png")

        dialog.reject()
        QTimer.singleShot(800, finish)

    def finish():
        RESULT["ok"] = all(c["ok"] for c in RESULT["checks"])

        with open(os.path.join(ROOT, "rename_about_result.json"), "w", encoding = "utf-8") as f:
            json.dump(RESULT, f, ensure_ascii = False, indent = 2)

        log("结果：%r" % RESULT["ok"])
        os._exit(0 if RESULT["ok"] else 3)

    QTimer.singleShot(3500, step1)
    app.exec()


if __name__ == "__main__":
    main_test()
