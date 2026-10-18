# -*- coding: utf-8 -*-
"""
内置浏览器页（WebView2 内核）

设计要点：
  * 懒加载：只有第一次切到这一页才会加载 WebView2Loader / 创建环境，不影响启动耗时；
  * 窗口尺寸不动，网页用 ZoomFactor 自动适配（B 站是固定宽布局，窄窗口必须缩小）；
  * 登录态：打开后把 config.json 里的 cookie 通过 JS 注入，刷新即为已登录账号；
  * 底部「下载该页面的项目」：取当前 URL → 校验能否解析 → signal_bus.parse.parse_url
    → 主窗口自动切到解析页并解析（复用现有链路）。
"""

import ctypes
import logging
import os

from PySide6.QtCore import Qt, QTimer, QUrl, QEvent, QPoint
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QStackedLayout, QApplication, QDialog

from qfluentwidgets import FluentIcon, PrimaryPushButton, BodyLabel, StrongBodyLabel, HyperlinkLabel

from ..component.browser import BrowserToolBar

from util.browser import WebView2, is_available, get_runtime_version
from util.browser.cookies import build_inject_script
from util.browser.url import is_parseable
from util.common.config import config, appdata_path
from util.common.enum import ToastNotificationCategory
from util.common.signal_bus import signal_bus
from util.common.translator import localize

logger = logging.getLogger(__name__)

DEFAULT_HOME = "https://www.bilibili.com/"
WEBVIEW2_DOWNLOAD_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

FIT_JS = "(() => { const de = document.documentElement; return {cw: de.clientWidth, sw: de.scrollWidth, bw: document.body ? document.body.scrollWidth : 0}; })()"


class BrowserInterface(QFrame):
    def __init__(self, parent = None):
        super().__init__(parent)

        self.setObjectName("BrowserInterface")

        self._bridge = None
        self._ready = False
        self._injected = False
        self._auto_zoom = True
        self._zoom = 1.0
        self._current_url = ""
        self._fit_timer = None
        self._state_timer = None
        self._overlay_timer = None
        self._overlay_hidden = False

        self.init_UI()

    # ---------- UI ----------

    def init_UI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self.toolbar = BrowserToolBar(self)

        self.host = QWidget(self)
        self.host.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.host.setMinimumHeight(160)
        self.host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.fallback_widget = self._build_fallback_widget()

        self.stack = QStackedLayout()
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.host)
        self.stack.addWidget(self.fallback_widget)

        host_container = QWidget(self)
        host_container.setLayout(self.stack)

        self.status_label = BodyLabel("", self)
        self.status_label.setStyleSheet("color: rgba(128, 128, 128, 0.9);")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.download_btn = PrimaryPushButton(
            localize("下载该页面的项目", "下載此頁面的項目", "Download items from this page"),
            self,
            icon = FluentIcon.DOWNLOAD
        )

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.download_btn)

        layout.addWidget(self.toolbar)
        layout.addWidget(host_container, 1)
        layout.addLayout(bottom)

        self.connect_signals()

    def _build_fallback_widget(self) -> QWidget:
        widget = QWidget(self)

        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)

        title = StrongBodyLabel(localize("无法启动内置浏览器", "無法啟動內建瀏覽器", "Built-in browser unavailable"), widget)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.fallback_label = BodyLabel("", widget)
        self.fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fallback_label.setWordWrap(True)

        self.fallback_link = HyperlinkLabel(
            localize("前往下载 Microsoft Edge WebView2 Runtime", "前往下載 Microsoft Edge WebView2 Runtime",
                     "Download Microsoft Edge WebView2 Runtime"),
            widget
        )
        self.fallback_link.setUrl(WEBVIEW2_DOWNLOAD_URL)

        layout.addWidget(title)
        layout.addWidget(self.fallback_label)
        layout.addWidget(self.fallback_link, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(2)

        widget.hide()

        return widget

    def connect_signals(self):
        self.toolbar.back_btn.clicked.connect(lambda: self._bridge and self._bridge.go_back())
        self.toolbar.forward_btn.clicked.connect(lambda: self._bridge and self._bridge.go_forward())
        self.toolbar.reload_btn.clicked.connect(lambda: self._bridge and self._bridge.reload())
        self.toolbar.home_btn.clicked.connect(self._go_home)
        self.toolbar.external_btn.clicked.connect(self._open_external)

        self.toolbar.address_edit.returnPressed.connect(self._on_address_entered)
        self.toolbar.zoom_out_btn.clicked.connect(lambda: self._apply_zoom(self._zoom * 0.9, manual = True))
        self.toolbar.zoom_in_btn.clicked.connect(lambda: self._apply_zoom(self._zoom * 1.1, manual = True))
        self.toolbar.zoom_label.installEventFilter(self)

        self.download_btn.clicked.connect(self._on_download_clicked)

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_zoom)

    def eventFilter(self, obj, event):
        if obj is self.toolbar.zoom_label and event.type() == QEvent.Type.MouseButtonPress:
            self._auto_zoom = True
            self._fit_zoom()
            return True

        return super().eventFilter(obj, event)

    # ---------- 生命周期 ----------

    def showEvent(self, event):
        super().showEvent(event)

        QTimer.singleShot(30, self._ensure_bridge)

        if self._ready and not self._overlay_hidden:
            QTimer.singleShot(60, self._resume_webview)

    def _resume_webview(self):
        """从隐藏状态切回浏览器页时，把网页窗口、bounds、缩放恢复回来"""
        if self._bridge is None or not self._bridge.ready:
            return

        self.host.show()
        self._bridge.set_visible(True)
        self._apply_bounds()

        if self._auto_zoom:
            self._fit_timer.start(200)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        self._apply_bounds()

        if self._ready and self._auto_zoom:
            self._fit_timer.start(400)

    def _ensure_bridge(self):
        if self._bridge is not None:
            return

        runtime = get_runtime_version()

        if not runtime:
            self._show_fallback(
                localize("系统未检测到 Microsoft Edge WebView2 Runtime，内置浏览器无法使用。",
                         "系統未偵測到 Microsoft Edge WebView2 Runtime，內建瀏覽器無法使用。",
                         "Microsoft Edge WebView2 Runtime is not installed, so the built-in browser cannot work.")
            )
            return

        logger.info("启动内建浏览器，WebView2 Runtime %s", runtime)

        self.host.show()
        self.fallback_widget.hide()
        self.stack.setCurrentWidget(self.host)

        user_data_dir = os.path.join(appdata_path, "Bili23 Downloader", "browser")

        self._bridge = WebView2(user_data_dir)
        self._bridge.create(
            int(self.host.winId()),
            on_ready = self._on_ready,
            on_navigation_completed = self._on_navigation_completed,
            on_new_window = self._on_new_window,
            on_fullscreen_changed = self._on_fullscreen_changed,
            on_error = self._on_error
        )

        self._state_timer = QTimer(self)
        self._state_timer.timeout.connect(self._poll_state)
        self._state_timer.start(900)

        # 有 Qt 蒙层对话框出现时要把网页窗口藏起来，否则原生子窗口会盖住对话框
        self._overlay_timer = QTimer(self)
        self._overlay_timer.timeout.connect(self._check_overlay)
        self._overlay_timer.start(150)

        app = QApplication.instance()

        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def _show_fallback(self, message: str):
        self.fallback_label.setText(message)
        self.stack.setCurrentWidget(self.fallback_widget)
        self.fallback_widget.show()
        self.host.hide()

        self.status_label.setText(message)

    def shutdown(self):
        if self._state_timer is not None:
            self._state_timer.stop()

        if self._overlay_timer is not None:
            self._overlay_timer.stop()

        if self._bridge is not None:
            try:
                self._bridge.shutdown()

            except Exception:
                logger.exception("关闭内建浏览器失败")

            self._bridge = None
            self._ready = False

    # ---------- 事件回调 ----------

    def _on_ready(self):
        self._ready = True

        logger.info("WebView2 初始化完成")

        self._apply_bounds()
        self._apply_zoom(1.0, manual = False)
        self._go_home()

    def _on_navigation_completed(self):
        if not self._ready:
            return

        if not self._injected:
            self._inject_cookies()
            return

        if self._auto_zoom:
            self._fit_timer.start(300)

        self._poll_state()

    def _on_new_window(self, uri: str):
        logger.info("页面请求打开新窗口，改为当前页打开：%s", uri)

        if uri:
            self.navigate(uri)

    def _on_fullscreen_changed(self, fullscreen: bool):
        window = self.window()

        if window is None:
            return

        try:
            if fullscreen:
                window.showFullScreen()
            else:
                window.showNormal()

        except Exception:
            logger.exception("切换全屏失败")

    def _on_error(self, message: str):
        logger.error("WebView2 错误：%s", message)

        self._show_fallback(message)

    # ---------- 登录态 ----------

    def _inject_cookies(self):
        self._injected = True

        if self._bridge is None or not self._bridge.ready:
            return

        logger.info("向内建浏览器注入登录 Cookie")

        self._bridge.run_js_async(build_inject_script())

        # 写完 cookie 刷新一次，让服务端看到登录态
        QTimer.singleShot(250, lambda: self._bridge and self._bridge.reload())

    # ---------- 缩放 ----------

    def _fit_zoom(self):
        if self._bridge is None or not self._ready:
            return

        def on_measure(value):
            if not value:
                return

            avail = value.get("cw") or 1
            content = max(value.get("sw") or 0, value.get("bw") or 0)

            if content <= 0 or avail <= 0:
                return

            zoom = 1.0 if content <= avail else max(0.5, min(1.0, (avail - 4) / content))

            self._apply_zoom(zoom, manual = False)

            def on_verify(verify):
                if not verify:
                    return

                cw = verify.get("cw") or 1
                sw = max(verify.get("sw") or 0, verify.get("bw") or 0)

                if sw > cw + 1:
                    tighter = max(0.5, min(1.0, (cw - 4) / sw)) * self._zoom
                    self._apply_zoom(tighter, manual = False)

            QTimer.singleShot(350, lambda: self._bridge and self._bridge.run_js(FIT_JS, on_verify))

        self._bridge.run_js(FIT_JS, on_measure)

    def _apply_zoom(self, zoom: float, manual: bool):
        zoom = round(max(0.5, min(2.0, zoom)), 3)

        if manual:
            self._auto_zoom = False

        self._zoom = zoom

        if self._bridge is not None and self._bridge.ready:
            self._bridge.set_zoom(zoom)

        self.toolbar.set_zoom_text(zoom)

    # ---------- 导航 ----------

    def _home_url(self) -> str:
        url = ""

        try:
            url = config.get(config.browser_home_url) or ""

        except Exception:
            url = ""

        return url or DEFAULT_HOME

    def _go_home(self):
        self.navigate(self._home_url())

    def navigate(self, url: str):
        if not url:
            return

        url = url.strip()

        if not url.lower().startswith(("http://", "https://", "b23.tv", "bili23://")):
            url = "https://" + url

        self._current_url = url
        self.toolbar.set_address(url)

        if self._bridge is not None and self._bridge.ready:
            self._bridge.navigate(url)

    def _on_address_entered(self):
        self.navigate(self.toolbar.address_edit.text())

    def _open_external(self):
        if self._current_url:
            QDesktopServices.openUrl(QUrl(self._current_url))

    # ---------- 原生子窗口与 Qt 蒙层的层级协调 ----------

    def _has_qt_overlay(self) -> bool:
        """当前是否有盖在本窗口上的非原生对话框/蒙层（qfluentwidgets 的 MaskDialogBase 属于这种）"""
        app = QApplication.instance()

        if app is None:
            return False

        window = self.window()

        for widget in app.allWidgets():
            if widget is self or widget is window or self.isAncestorOf(widget):
                continue

            if not isinstance(widget, QDialog) or not widget.isVisible():
                continue

            # 原生顶层对话框本来就在网页上面，不需要藏网页
            if widget.isWindow():
                continue

            if widget.window() is window:
                return True

        return False

    def _check_overlay(self):
        if self._bridge is None or not self._bridge.ready:
            return

        has_overlay = self._has_qt_overlay()

        if has_overlay == self._overlay_hidden:
            return

        self._overlay_hidden = has_overlay

        # 关键：WebView2 的宿主 host 本身是原生子窗口（WA_NativeWindow），
        # 只调 put_IsVisible(FALSE) 的话宿主 HWND 还在，仍然盖在 qfluentwidgets
        # 的蒙层对话框上面吃鼠标事件 —— 表现为"弹窗能看见但点不动"（键盘却能用）。
        # 所以宿主 widget 也要从 Qt 层隐藏。
        try:
            if has_overlay:
                # 网页原先把鼠标捕获抓在自己手里，藏起来后要主动释放，否则点击
                # 仍然被送进隐藏窗口，表现为"对话框能看见但点不动"
                try:
                    ctypes.windll.user32.ReleaseCapture()

                except Exception:
                    pass

            # 必须藏整个浏览器页，而不是只藏 host：
            # 为了给 WebView2 提供 HWND，Qt 会把 host 的一串祖先控件（host_container、
            # BrowserInterface、StackedWidget…）都变成原生窗口，只藏 host 的话这些
            # 原生窗口仍然可见，依旧盖在 qfluentwidgets 的蒙层对话框上面吃鼠标点击。
            if has_overlay:
                self._bridge.set_visible(False)

                # 不是只藏自己：为了给 WebView2 提供 HWND，Qt 会把整条祖先链
                # （host_container → BrowserInterface → StackedWidget…）都变成原生窗口，
                # 只藏 BrowserInterface 的话它的父级原生窗口仍在，依旧会吃掉弹窗的鼠标点击。
                # 所以往上找到"主窗口的直接子控件"整棵藏掉，弹窗关掉后再恢复。
                target = self
                parent = self.parentWidget()
                main_window = self.window()

                while parent is not None and parent is not main_window:
                    target = parent
                    parent = parent.parentWidget()

                self._overlay_target = target
                # 记住隐藏前这一页是否可见：只有本来就可见，恢复时才显示。
                # 否则（比如当前在解析页时开了「关于」对话框）恢复时会把浏览器页
                # 强行 show() 出来，叠在解析页上造成重叠。
                self._overlay_was_visible = self.isVisible()

                target.setVisible(False)

            else:
                target = getattr(self, "_overlay_target", None)

                if target is not None:
                    target.setVisible(True)

                if getattr(self, "_overlay_was_visible", False):
                    self.show()
                    self.host.show()
                    self._bridge.set_visible(True)

                else:
                    # 这一页当时没显示，保持隐藏；等用户切回来时由 showEvent 恢复
                    self.hide()
                    self.host.hide()
                    self._bridge.set_visible(False)

        except Exception:
            logger.exception("切换网页可见性失败")

        if not has_overlay and getattr(self, "_overlay_was_visible", False):
            # 重新显示时补一次 bounds / 缩放，防止隐藏期间窗口尺寸变了
            QTimer.singleShot(80, self._apply_bounds)
            QTimer.singleShot(80, lambda: self._auto_zoom and self._fit_timer.start(200))
    # ---------- 状态 ----------

    def _poll_state(self):
        if self._bridge is None or not self._bridge.ready:
            return

        def on_state(value):
            if not value:
                return

            url = value.get("url") or ""

            if url and url != "about:blank":
                self._current_url = url
                self.toolbar.set_address(url)

            title = value.get("title") or ""
            self.status_label.setText(title if title else url)

            try:
                self.toolbar.set_nav_state(self._bridge.can_go_back(), self._bridge.can_go_forward())

            except Exception:
                pass

        self._bridge.run_js("({url: location.href, title: document.title, ready: document.readyState})", on_state)

    def _apply_bounds(self):
        if self._bridge is None or not self._bridge.ready:
            return

        dpr = self.devicePixelRatioF()
        width = int(round(self.host.width() * dpr))
        height = int(round(self.host.height() * dpr))

        if width <= 0 or height <= 0:
            return

        self._bridge.set_bounds(0, 0, width, height)

    # ---------- 下载按钮 ----------

    def _on_download_clicked(self):
        url = self._current_url

        if not url:
            self._show_toast(
                ToastNotificationCategory.WARNING,
                localize("没有可解析的页面", "沒有可解析的頁面", "No page to parse"),
                localize("请先在内置浏览器里打开一个 B 站视频页面。",
                         "請先在建置瀏覽器裡開啟一個 B 站影片頁面。",
                         "Open a Bilibili video page in the built-in browser first.")
            )
            return

        if not is_parseable(url):
            self._show_toast(
                ToastNotificationCategory.WARNING,
                localize("当前页面无法解析", "目前頁面無法解析", "This page cannot be parsed"),
                localize("请在视频、番剧、课程、收藏夹等页面使用该按钮。",
                         "請在影片、番劇、課程、收藏夾等頁面使用該按鈕。",
                         "Use this button on a video, bangumi, course or favorites page.")
            )
            return

        logger.info("从内建浏览器发起解析：%s", url)

        signal_bus.parse.parse_url.emit(url)

    def _show_toast(self, category, title: str, content: str):
        signal_bus.toast.show.emit(category, title, content)
