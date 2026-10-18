# -*- coding: utf-8 -*-
r"""
回归：下载数量红点必须挂在「下载」导航项上，而不是「浏览器」上

做法：
  1. 起真实 MainWindow；
  2. 调用 update_download_btn_badge_info(5) 让红点显示；
  3. 断言红点的中心与 download_btn 中心的距离很小，且离 browser_btn 明显更远；
  4. 截图留证；再调用 0 隐藏，断言已隐藏。

运行：
    "D:\Bili23 Downloader\runtime\python.exe" -u tools\test_download_badge.py
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

STATE = {"start": time.time()}
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

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication

    from gui.interface.main_window import MainWindow

    window = MainWindow()
    app.window = window

    def center_of(widget):
        top_left = widget.mapToGlobal(QPoint(0, 0))
        return QPoint(top_left.x() + widget.width() // 2, top_left.y() + widget.height() // 2)

    def run():
        badge = window.download_info_badge

        # 先断言：没有下载任务时红点必须隐藏（之前管理器会在按钮 Show 时把初始 "99+" 显示出来）
        app.processEvents()
        time.sleep(0.3)
        app.processEvents()

        # 切几次页面，触发导航按钮的 Show 事件
        for key in ("ParseInterface", "BrowserInterface", "ParseInterface"):
            if key in window.navigationInterface.items:
                window.navigationInterface.items[key].click()
            app.processEvents()
            time.sleep(0.15)

        check("没有下载任务时红点隐藏（不会显示 99+）", badge.isHidden())

        window.update_download_btn_badge_info(5)

        app.processEvents()
        time.sleep(0.4)
        app.processEvents()

        check("红点已显示", not badge.isHidden())

        badge_center = center_of(badge)
        download_center = center_of(window.download_btn)
        browser_center = center_of(window.browser_btn)

        d_download = (badge_center - download_center).manhattanLength()
        d_browser = (badge_center - browser_center).manhattanLength()

        log("红点中心=%r 下载按钮中心=%r 浏览器按钮中心=%r" % (
            (badge_center.x(), badge_center.y()),
            (download_center.x(), download_center.y()),
            (browser_center.x(), browser_center.y())))
        log("到下载按钮距离=%d，到浏览器按钮距离=%d" % (d_download, d_browser))

        check("红点靠近下载按钮（<=60px）", d_download <= 60, d_download)
        check("红点明显更靠近下载按钮而不是浏览器", d_download < d_browser, (d_download, d_browser))

        rect = window.frameGeometry()
        pix = QGuiApplication.primaryScreen().grabWindow(0, rect.left(), rect.top(), rect.width(), rect.height())
        path = os.path.join(ROOT, "docs", "40_download_badge.png")
        pix.save(path, "PNG")
        log("截图：%s" % path)

        window.update_download_btn_badge_info(0)
        app.processEvents()
        check("数量归零后红点隐藏", badge.isHidden())

        RESULT["ok"] = all(c["ok"] for c in RESULT["checks"])

        with open(os.path.join(ROOT, "download_badge_result.json"), "w", encoding = "utf-8") as f:
            json.dump(RESULT, f, ensure_ascii = False, indent = 2)

        log("结果：%r" % RESULT["ok"])

        os._exit(0 if RESULT["ok"] else 3)

    QTimer.singleShot(3000, run)

    app.exec()


if __name__ == "__main__":
    main_test()
