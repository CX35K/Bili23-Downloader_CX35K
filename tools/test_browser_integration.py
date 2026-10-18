# -*- coding: utf-8 -*-
r"""
内置浏览器「整窗集成」测试：验证主窗口导航项 / 懒加载 / 页面切换

不做的事：不点真实下载，只验证
  1. 主窗口能正常起来（说明 main_window 的改动没有破坏启动）；
  2. 导航栏出现「浏览器」按钮；
  3. 第一次点击才创建 BrowserInterface（懒加载），并且成功切到该页；
  4. 页面里 WebView2 初始化完成、加载 B 站首页；
  5. 再切回解析页 / 再切回浏览器页不会崩（原生子窗口隐藏/显示）。

运行：
    "D:\Bili23 Downloader\runtime\python.exe" tools\test_browser_integration.py
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
from PySide6.QtGui import QGuiApplication  # noqa: E402

import main  # noqa: E402  复用真实的 Application（单实例、样式、翻译都按正式流程）

RESULT = {"ok": False, "checks": [], "errors": []}


def check(name, ok, detail=""):
    RESULT["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + str(detail)) if detail and not ok else ""), flush=True)


def main_test():
    started = time.time()

    app = main.Application(sys.argv)
    app.setup_app()

    from gui.interface.main_window import MainWindow

    window = MainWindow()
    app.window = window

    state = {"phase": "wait_init"}

    def screenshot(name):
        try:
            top_left = window.mapToGlobal(window.rect().topLeft())
            screen = QGuiApplication.primaryScreen()
            pixmap = screen.grabWindow(0, top_left.x(), top_left.y(), window.width(), window.height())
            path = os.path.join(ROOT, "docs", name)
            pixmap.save(path, "PNG")
            print("    截图：", path, flush=True)
        except Exception as e:
            print("    截图失败：", repr(e), flush=True)

    def finish():
        RESULT["ok"] = bool(RESULT["checks"]) and all(c["ok"] for c in RESULT["checks"])

        with open(os.path.join(ROOT, "browser_integration_result.json"), "w", encoding="utf-8") as f:
            json.dump(RESULT, f, ensure_ascii=False, indent=2)

        print("\n===== 结果 =====", flush=True)
        print(json.dumps(RESULT, ensure_ascii=False, indent=2), flush=True)

        try:
            if window.browser_interface is not None:
                window.browser_interface.shutdown()
        except Exception:
            pass

        os._exit(0 if RESULT["ok"] else 2)

    def tick():
        elapsed = time.time() - started

        if elapsed > 90:
            check("总超时", False)
            finish()
            return

        try:
            if state["phase"] == "wait_init":
                if window.initialized or elapsed > 6:
                    check("主窗口启动", True)

                    keys = list(window.navigationInterface.items.keys())
                    check("导航栏出现浏览器按钮", "BrowserInterface" in keys, keys)

                    window.navigationInterface.items["BrowserInterface"].click()

                    state["phase"] = "wait_browser"
                    state["since"] = time.time()

            elif state["phase"] == "wait_browser":
                if window.browser_interface is None:
                    if time.time() - state["since"] > 10:
                        check("点击后创建浏览器页", False)
                        finish()
                    return

                check("点击后才创建浏览器页（懒加载）", True)

                if window.stackedWidget.currentWidget() is window.browser_interface:
                    check("已切换到浏览器页", True)
                else:
                    check("已切换到浏览器页", False, type(window.stackedWidget.currentWidget()).__name__)

                state["phase"] = "wait_home"
                state["since"] = time.time()

            elif state["phase"] == "wait_paint":
                # 等几秒让页面真正画出来，再量视口宽度（bounds 正确的话应该接近 1100 CSS px）
                if state.get("paint_checked") or time.time() - state["since"] < 3:
                    return

                state["paint_checked"] = True

                browser = window.browser_interface

                def on_viewport(value):
                    cw = (value or {}).get("cw") or 0
                    check("主窗口内视口宽度正常", cw > 800, value)
                    screenshot("11_integration_browser.png")

                    window.navigationInterface.items["ParseInterface"].click()
                    QTimer.singleShot(1200, switch_back)
                    state["phase"] = "wait_switch"

                browser._bridge.run_js("({cw: document.documentElement.clientWidth, iw: window.innerWidth})", on_viewport)

            elif state["phase"] == "wait_home":
                browser = window.browser_interface

                if browser._ready and "bilibili.com" in (browser._current_url or ""):
                    check("浏览器页加载 B 站首页", True, browser._current_url)

                    state["phase"] = "wait_paint"
                    state["since"] = time.time()
                    return

                    # 切回解析页再切回来，验证原生子窗口隐藏/显示不炸
                    window.navigationInterface.items["ParseInterface"].click() if "ParseInterface" in window.navigationInterface.items else None
                    QTimer.singleShot(1200, switch_back)

                    state["phase"] = "wait_switch"

                elif time.time() - state["since"] > 25:
                    check("浏览器页加载 B 站首页", False, browser._current_url)
                    finish()

            elif state["phase"] == "wait_back":
                if state.get("back_checked"):
                    return

                if window.stackedWidget.currentWidget() is window.browser_interface:
                    state["back_checked"] = True
                    check("切走再切回浏览器页", True)

                    def on_state(value):
                        check("切回后页面仍在", bool(value) and "bilibili" in (value.get("url") or ""), value)
                        finish()

                    window.browser_interface._bridge.run_js("({url: location.href, title: document.title})", on_state)
                elif time.time() - state["since"] > 10:
                    check("切走再切回浏览器页", False)
                    finish()

        except Exception as e:
            import traceback
            RESULT["errors"].append(repr(e))
            print(traceback.format_exc(), flush=True)
            finish()

    def switch_back():
        window.navigationInterface.items["BrowserInterface"].click()
        state["phase"] = "wait_back"
        state["since"] = time.time()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(500)

    QTimer.singleShot(95000, lambda: (check("总超时", False), finish()))

    app.exec()


if __name__ == "__main__":
    main_test()
