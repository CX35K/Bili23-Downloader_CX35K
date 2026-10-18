# -*- coding: utf-8 -*-
r"""
内置浏览器页集成测试（会弹出真实窗口，约 25 秒）

验证：
  1. BrowserInterface 能创建 WebView2、打开 B 站首页；
  2. 自动登录：注入 cookie 后 api nav 返回 isLogin；
  3. 自动缩放：页面无横向溢出（scrollWidth <= clientWidth）；
  4. 视频页能拿到 video 元素并播放；
  5. 「下载该页面的项目」按钮把当前 URL 通过 signal_bus.parse.parse_url 发出去；
  6. 截图留证。

运行：
    "D:\Bili23 Downloader\runtime\python.exe" tools\test_browser_page.py
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")

# --src 指定源码目录（默认 src）。传 "D:\\Bili23 Downloader\\patch" 可以验证部署后的补丁层代码
TARGET_SRC = SRC
if "--src" in sys.argv:
    TARGET_SRC = sys.argv[sys.argv.index("--src") + 1]

if TARGET_SRC == SRC:
    sys.path.insert(0, SRC)
    sys.path.insert(0, ROOT)

    import launcher  # noqa: E402  复用 PYSTAND 环境变量设置
else:
    HOME = os.environ.get("BILI23_HOME") or r"D:\Bili23 Downloader"
    os.environ.setdefault("PYSTAND", os.path.join(HOME, "Bili23.exe"))
    os.environ.setdefault("PYSTAND_HOME", HOME)
    os.environ.setdefault("PYSTAND_RUNTIME", os.path.join(HOME, "runtime"))
    os.environ.setdefault("PYSTAND_SCRIPT", os.path.join(TARGET_SRC, "main.py"))

    sys.path.insert(0, TARGET_SRC)

    for sub in (".", "lib", "site-packages", "runtime"):
        path = os.path.abspath(os.path.join(HOME, sub))
        if os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)

    site = os.path.join(HOME, "site-packages")
    for sub in (("win32",), ("win32", "lib"), ("Pythonwin",)):
        path = os.path.join(site, *sub)
        if os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)

    try:
        import pywin32_bootstrap  # noqa: F401
    except ImportError:
        pass

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from gui.interface.browser import BrowserInterface  # noqa: E402
from util.browser.cookies import build_login_probe_script  # noqa: E402
from util.common.signal_bus import signal_bus  # noqa: E402

VIDEO_URL = "https://www.bilibili.com/video/BV1GJ411x7h7"
SHOT_DIR = os.path.join(ROOT, "docs")

RESULT = {"ok": False, "checks": [], "errors": []}


def check(name, ok, detail=""):
    RESULT["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + str(detail)) if detail and not ok else ""), flush=True)


def main():
    started = time.time()

    app = QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("Bili23 内置浏览器测试")
    window.resize(950, 600)

    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)

    browser = BrowserInterface(window)
    layout.addWidget(browser)

    window.show()

    captured = {"url": None}
    signal_bus.parse.parse_url.connect(lambda url: captured.update(url=url))

    state = {"phase": "wait_ready", "login": None, "zoom": None, "video": None}

    def screenshot(name):
        try:
            top_left = window.mapToGlobal(window.rect().topLeft())
            screen = QGuiApplication.primaryScreen()
            pixmap = screen.grabWindow(0, top_left.x(), top_left.y(), window.width(), window.height())
            path = os.path.join(SHOT_DIR, name)
            pixmap.save(path, "PNG")
            print("    截图：", path, "%dx%d" % (pixmap.width(), pixmap.height()), flush=True)
        except Exception as e:
            print("    截图失败：", repr(e), flush=True)

    def tick():
        elapsed = time.time() - started

        if elapsed > 90:
            check("总超时", False)
            finish()
            return

        if state["phase"] == "wait_ready":
            if browser._bridge is not None and browser._ready:
                check("WebView2 初始化", True, "runtime=%s" % browser._bridge and "")
                state["phase"] = "wait_home"
                state["since"] = time.time()

        elif state["phase"] == "wait_home":
            url = browser._current_url or ""

            if "bilibili.com" in url and time.time() - state["since"] > 12:
                check("打开 B 站首页", True, url)
                screenshot("9_browser_page_home.png")
                state["phase"] = "wait_login"
                state["since"] = time.time()

                browser._bridge.run_js_async(build_login_probe_script())

        elif state["phase"] == "wait_login":
            def on_login(value):
                if value and not state["login"]:
                    state["login"] = value
                    check("自动登录", bool(value.get("isLogin")), value)
                    state["phase"] = "zoom_check"
                    state["since"] = time.time()

            if browser._bridge and browser._bridge.ready:
                browser._bridge.run_js("window.__bili23_login ? window.__bili23_login : null", on_login)

        elif state["phase"] == "zoom_check":
            if time.time() - state["since"] < 2:
                return

            def on_measure(value):
                if not value:
                    return

                cw = value.get("cw") or 0
                sw = max(value.get("sw") or 0, value.get("bw") or 0)

                state["zoom"] = {"clientWidth": cw, "contentWidth": sw, "zoom": browser._zoom}
                check("自动缩放后无横向溢出", sw <= cw + 1, state["zoom"])

                state["phase"] = "video"
                state["since"] = time.time()

                browser.navigate(VIDEO_URL)

            browser._bridge.run_js(
                "(() => { const de = document.documentElement; return {cw: de.clientWidth, sw: de.scrollWidth, bw: document.body ? document.body.scrollWidth : 0}; })()",
                on_measure
            )
            state["phase"] = "zoom_wait"

        elif state["phase"] == "wait_video":
            if time.time() - state["since"] < 8:
                return

            def on_video(value):
                state["video"] = value
                playing = bool(value) and (value.get("currentTime") or 0) > 0.5

                check("视频元素存在且播放", playing, value)

                screenshot("10_browser_page_video.png")

                # 点「下载该页面的项目」
                browser.download_btn.click()

                QTimer.singleShot(1500, check_download)

            browser._bridge.run_js(
                "(() => { const v = document.querySelector('video');"
                " if (v) { v.muted = true; v.play().catch(() => {}); }"
                " return v ? {readyState: v.readyState, currentTime: v.currentTime,"
                " duration: v.duration, width: v.videoWidth} : null; })()",
                on_video
            )
            state["phase"] = "video_wait"

    def check_download():
        url = captured["url"]

        check("「下载该页面的项目」发出解析 URL", url == VIDEO_URL or (url and "/video/" in url), url)

        finish()

    def finish():
        RESULT["ok"] = not RESULT["errors"] and all(c["ok"] for c in RESULT["checks"])

        with open(os.path.join(ROOT, "browser_test_result.json"), "w", encoding="utf-8") as f:
            json.dump(RESULT, f, ensure_ascii=False, indent=2)

        print("\n===== 结果 =====", flush=True)
        print(json.dumps(RESULT, ensure_ascii=False, indent=2), flush=True)

        try:
            browser.shutdown()

        except Exception:
            pass

        app.quit()
        os._exit(0 if RESULT["ok"] else 2)

    # phase 推进：wait_video 由 navigate 后进入
    original_tick = tick

    def tick_wrapper():
        if state["phase"] == "video":
            state["phase"] = "wait_video"
            state["since"] = time.time()
        original_tick()

    timer = QTimer()
    timer.timeout.connect(tick_wrapper)
    timer.start(400)

    QTimer.singleShot(95000, lambda: (check("总超时", False), finish()))

    app.exec()


if __name__ == "__main__":
    main()
