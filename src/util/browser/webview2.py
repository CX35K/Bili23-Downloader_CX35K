#-*- coding: utf-8 -*-
"""
WebView2 的 ctypes COM 桥（不依赖 .NET / pywebview）

为什么自己写：
  PySide6 的 QtWebEngine 轮子没编译 H.264/AAC 专有编解码器，B 站网页播不了视频；
  WebView2（Edge 内核）编解码齐全、系统自带 Runtime，只需要一个 195KB 的
  WebView2Loader.dll 就能从 Python 直连 COM 把网页挂到 Qt 控件的 HWND 上。

关键实现约束（都是踩过的坑）：
  * COM 回调 Invoke 必须显式返回 0；Python 返回 None 会被 ctypes 吞掉，
    表现为"回调执行了但后面没反应"。
  * 环境/控制器指针在完成回调返回后可能被释放，要留到回调之外使用必须先 AddRef。
  * ExecuteScript 的结果是 LPCWSTR 指针，得 wstring_at 转字符串；
    想拿 JS 对象统一 JSON.stringify 再传回来。
  * 窗口是 Qt 逻辑像素、WebView2 要物理像素，set_bounds 内部乘 devicePixelRatio。

对外接口（GUI 线程使用）：
  WebView2(loader_path, user_data_dir)
      .create(hwnd, on_ready, on_navigation_completed, on_new_window, on_fullscreen_changed, on_error)
      .set_bounds(x, y, width, height)      # 物理像素
      .navigate(url) / .reload() / .go_back() / .go_forward() / .stop()
      .can_go_back() / .can_go_forward()
      .set_zoom(zoom) / .get_zoom()
      .run_js(expression, callback)         # callback 拿到解析后的 Python 对象
      .shutdown()
"""

import ctypes
import json
import logging
import os
import sys
from ctypes import wintypes

from ..common.config import appdata_path
from ..common.io.directory import Directory

HRESULT = ctypes.c_long
S_OK = 0
E_NOINTERFACE = -2147467262

IIDS = {
    "env_handler": "4e8a3389-c9d8-4bd2-b6b5-124fee6cc14d",
    "controller_handler": "6c4819f3-c9b7-4260-8127-c9f5bde7f68c",
    "script_handler": "49511172-cc67-4bca-9923-137112f4c4cc",
    "navigation_handler": "d33a35bf-1c49-4f98-93ab-006e0533fe1c",
    "new_window_handler": "d4c185fe-c81c-4989-97af-2d3fa7ab5651",
    "new_window_args": "34acb11c-fc37-4418-9132-f9c21d1eafb9",
    "fullscreen_handler": "e45d98b1-afef-45be-8baf-6c7728867f73",
}

# vtable 序号：来自 Microsoft.Web.WebView2 1.0.4258.31 的 WebView2.h
ENV_CREATE_CONTROLLER = 3

CTRL_PUT_VISIBLE = 4
CTRL_PUT_BOUNDS = 6
CTRL_GET_ZOOM = 7
CTRL_PUT_ZOOM = 8
CTRL_CLOSE = 24
CTRL_GET_WEBVIEW = 25

WV_GET_SETTINGS = 3
WV_NAVIGATE = 5
WV_ADD_NAV_COMPLETED = 15
WV_EXECUTE_SCRIPT = 29
WV_RELOAD = 31
WV_CAN_GO_BACK = 38
WV_CAN_GO_FORWARD = 39
WV_GO_BACK = 40
WV_GO_FORWARD = 41
WV_STOP = 43
WV_ADD_NEW_WINDOW_REQUESTED = 44
WV_ADD_FULLSCREEN_CHANGED = 52
WV_GET_FULLSCREEN = 54

NW_ARGS_GET_URI = 3
NW_ARGS_PUT_HANDLED = 6

SETTINGS_PUT_ZOOM_CONTROL = 18


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8),
    ]


def _make_guid(text: str) -> GUID:
    a, b, c, d, e = text.split("-")
    guid = GUID()
    guid.Data1 = int(a, 16)
    guid.Data2 = int(b, 16)
    guid.Data3 = int(c, 16)

    for i, byte in enumerate(bytes.fromhex(d + e)):
        guid.Data4[i] = byte

    return guid


class ComHandler:
    """
    只含 IUnknown 三件套 + Invoke 的最小 COM 对象

    注意 Invoke 的第二参数在不同事件里类型不同：
      * 完成回调（环境/控制器/ExecuteScript）：中间是 HRESULT
      * 事件回调（导航完成/新窗口/全屏）：中间是 sender 接口指针
    两者都按指针声明会让 HRESULT=0 变成 None，判断逻辑全废，所以这里分开建类型。
    """

    _QI = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
    _ADDREF = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
    _RELEASE = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)

    _INVOKE_HR = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, HRESULT, ctypes.c_void_p)
    _INVOKE_PTR = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

    def __init__(self, iid_text: str, invoke_cb, middle: str = "ptr"):
        self.iid = _make_guid(iid_text)
        self.ref_count = 1
        self.callback = invoke_cb

        def _invoke(this, first, second):
            try:
                invoke_cb(this, first, second)

            except Exception:
                logging.getLogger(__name__).exception("WebView2 事件回调异常")

            return 0

        self._qi_cb = self._QI(self._query_interface)
        self._add_cb = self._ADDREF(lambda this: self._ref(1))
        self._rel_cb = self._RELEASE(lambda this: self._ref(-1))

        invoke_type = self._INVOKE_HR if middle == "hr" else self._INVOKE_PTR
        self._invoke_cb = invoke_type(_invoke)

        self._vtable = (ctypes.c_void_p * 4)(
            ctypes.cast(self._qi_cb, ctypes.c_void_p).value,
            ctypes.cast(self._add_cb, ctypes.c_void_p).value,
            ctypes.cast(self._rel_cb, ctypes.c_void_p).value,
            ctypes.cast(self._invoke_cb, ctypes.c_void_p).value,
        )
        self._object = (ctypes.c_void_p * 1)(ctypes.addressof(self._vtable))

    def _ref(self, delta: int) -> int:
        self.ref_count += delta
        return self.ref_count

    def _query_interface(self, this, riid, ppv):
        requested = riid.contents if riid else None
        same = requested is not None and (
            requested.Data1 == self.iid.Data1 and requested.Data2 == self.iid.Data2
            and requested.Data3 == self.iid.Data3 and bytes(requested.Data4) == bytes(self.iid.Data4)
        )
        ppv[0] = this if same else None
        return S_OK if same else E_NOINTERFACE

    @property
    def pointer(self) -> int:
        return ctypes.addressof(self._object)


def loader_path() -> str:
    """
    WebView2Loader.dll 放在安装目录之外的用户数据目录里。

    原因：Bili23 的 PyStand 引导有安装完整性校验，往安装目录里新增文件
    （实测 bundle\WebView2Loader.dll）会被判成"Unexpected file"直接拒绝启动；
    放到 %APPDATA% 下既不影响校验，也不需要管理员权限。
    """
    override = os.environ.get("BILI23_WEBVIEW2_LOADER", "")

    candidates = []

    if override:
        candidates.append(override)

    candidates.append(os.path.join(appdata_path, "Bili23 Downloader", "browser", "WebView2Loader.dll"))
    candidates.append(os.path.join(Directory.get_cwd(), "bundle", "WebView2Loader.dll"))

    for path in candidates:
        if os.path.exists(path):
            return path

    return candidates[0]


def _load_loader():
    path = loader_path()

    if not os.path.exists(path):
        return None

    os.add_dll_directory(os.path.dirname(path))

    loader = ctypes.WinDLL(path)
    loader.GetAvailableCoreWebView2BrowserVersionString.restype = HRESULT
    loader.GetAvailableCoreWebView2BrowserVersionString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    loader.CreateCoreWebView2EnvironmentWithOptions.restype = HRESULT
    loader.CreateCoreWebView2EnvironmentWithOptions.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p
    ]

    return loader


def get_runtime_version() -> str:
    """返回已安装的 WebView2 Runtime 版本号；不可用返回空串"""
    loader = _load_loader()

    if loader is None:
        return ""

    out = ctypes.c_void_p()
    hr = loader.GetAvailableCoreWebView2BrowserVersionString(None, ctypes.byref(out))

    if hr != S_OK or not out.value:
        return ""

    version = ctypes.wstring_at(out.value)

    try:
        ctypes.WinDLL("ole32").CoTaskMemFree(out.value)

    except Exception:
        pass

    return version or ""


def is_available() -> bool:
    return bool(get_runtime_version())


class WebView2:
    """一个 WebView2 实例（= 浏览器页里的一块网页区域）"""

    def __init__(self, user_data_dir: str):
        self.user_data_dir = user_data_dir

        self.loader = None
        self.env = 0
        self.controller = 0
        self.webview = 0
        self.settings = 0

        self.ready = False
        self.closed = False

        self._handlers = []
        self._ole32 = ctypes.WinDLL("ole32")

        self.on_ready = None
        self.on_navigation_completed = None
        self.on_new_window = None
        self.on_fullscreen_changed = None
        self.on_error = None

    # ---------- 基础 ----------

    @staticmethod
    def call(ptr: int, index: int, restype, argtypes, *args):
        vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)

        return prototype(vtable[index])(ptr, *args)

    def _keep(self, handler: ComHandler) -> ComHandler:
        self._handlers.append(handler)
        return handler

    def _get_wstring(self, ptr: int, index: int) -> str:
        out = ctypes.c_void_p()
        hr = self.call(ptr, index, HRESULT, (ctypes.POINTER(ctypes.c_void_p),), ctypes.byref(out))

        if hr != S_OK or not out.value:
            return ""

        value = ctypes.wstring_at(out.value)

        try:
            self._ole32.CoTaskMemFree(out.value)

        except Exception:
            pass

        return value

    def _get_bool(self, ptr: int, index: int) -> bool:
        out = wintypes.BOOL()
        hr = self.call(ptr, index, HRESULT, (ctypes.POINTER(wintypes.BOOL),), ctypes.byref(out))

        return hr == S_OK and bool(out.value)

    # ---------- 创建 ----------

    def create(self, hwnd: int, on_ready=None, on_navigation_completed=None,
               on_new_window=None, on_fullscreen_changed=None, on_error=None):
        self._hwnd = hwnd
        self.on_ready = on_ready
        self.on_navigation_completed = on_navigation_completed
        self.on_new_window = on_new_window
        self.on_fullscreen_changed = on_fullscreen_changed
        self.on_error = on_error

        self.loader = _load_loader()

        if self.loader is None:
            self._error("找不到 WebView2Loader.dll（应在安装目录 bundle 下）")
            return

        version = get_runtime_version()

        if not version:
            self._error("系统未安装 WebView2 Runtime")
            return

        hr = self._ole32.CoInitializeEx(None, 0x2)  # STA；Qt 可能已经初始化过，S_FALSE 也算成功

        os.makedirs(self.user_data_dir, exist_ok = True)

        handler = self._keep(ComHandler(IIDS["env_handler"], self._on_environment_created, middle = "hr"))
        hr = self.loader.CreateCoreWebView2EnvironmentWithOptions(None, self.user_data_dir, None, handler.pointer)

        if hr != S_OK:
            self._error("创建 WebView2 环境失败（HRESULT=0x%08X）" % (hr & 0xFFFFFFFF))

    def _on_environment_created(self, this, hr, env_ptr):
        if hr != S_OK or not env_ptr:
            self._error("WebView2 环境创建失败（HRESULT=0x%08X）" % (hr & 0xFFFFFFFF))
            return

        # 回调返回后 loader 会释放自己那份引用，想继续用必须自己 AddRef
        self.call(env_ptr, 1, ctypes.c_ulong, ())
        self.env = env_ptr
        self._create_controller()

    def _create_controller(self):
        hwnd = int(self._hwnd)
        handler = self._keep(ComHandler(IIDS["controller_handler"], self._on_controller_created, middle = "hr"))

        hr = self.call(self.env, ENV_CREATE_CONTROLLER, HRESULT,
                       (ctypes.c_void_p, ctypes.c_void_p), hwnd, handler.pointer)

        if hr != S_OK:
            self._error("创建 WebView2 控制器失败（HRESULT=0x%08X）" % (hr & 0xFFFFFFFF))

    def _on_controller_created(self, this, hr, controller_ptr):
        if hr != S_OK or not controller_ptr:
            self._error("WebView2 控制器创建失败（HRESULT=0x%08X）" % (hr & 0xFFFFFFFF))
            return

        self.call(controller_ptr, 1, ctypes.c_ulong, ())
        self.controller = controller_ptr

        self.call(self.controller, CTRL_PUT_VISIBLE, HRESULT, (wintypes.BOOL,), True)

        webview = ctypes.c_void_p()
        hr = self.call(self.controller, CTRL_GET_WEBVIEW, HRESULT,
                       (ctypes.POINTER(ctypes.c_void_p),), ctypes.byref(webview))

        if hr != S_OK or not webview.value:
            self._error("拿不到 CoreWebView2 接口")
            return

        self.webview = webview.value

        self._init_settings()
        self._install_events()

        self.ready = True

        if self.on_ready is not None:
            self.on_ready()

    def _init_settings(self):
        settings = ctypes.c_void_p()
        hr = self.call(self.webview, WV_GET_SETTINGS, HRESULT,
                       (ctypes.POINTER(ctypes.c_void_p),), ctypes.byref(settings))

        if hr != S_OK or not settings.value:
            return

        self.call(settings.value, 1, ctypes.c_ulong, ())
        self.settings = settings.value

        # 允许 Ctrl+滚轮缩放（工具栏另有按钮）
        self.call(self.settings, SETTINGS_PUT_ZOOM_CONTROL, HRESULT, (wintypes.BOOL,), True)

    def _install_events(self):
        token = ctypes.c_longlong()

        handler = self._keep(ComHandler(IIDS["navigation_handler"], self._on_navigation_event))
        self.call(self.webview, WV_ADD_NAV_COMPLETED, HRESULT,
                  (ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)), handler.pointer, ctypes.byref(token))

        handler = self._keep(ComHandler(IIDS["new_window_handler"], self._on_new_window_event))
        self.call(self.webview, WV_ADD_NEW_WINDOW_REQUESTED, HRESULT,
                  (ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)), handler.pointer, ctypes.byref(token))

        handler = self._keep(ComHandler(IIDS["fullscreen_handler"], self._on_fullscreen_event))
        self.call(self.webview, WV_ADD_FULLSCREEN_CHANGED, HRESULT,
                  (ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)), handler.pointer, ctypes.byref(token))

    def _on_navigation_event(self, this, sender, args):
        if self.on_navigation_completed is not None:
            self.on_navigation_completed()

    def _on_new_window_event(self, this, sender, args):
        # 单页面浏览器：把 target=_blank / window.open 的链接留在当前页打开
        if not args:
            return

        uri = self._get_wstring(args, NW_ARGS_GET_URI)

        try:
            self.call(args, NW_ARGS_PUT_HANDLED, HRESULT, (wintypes.BOOL,), True)

        except Exception:
            pass

        if uri:
            if self.on_new_window is not None:
                self.on_new_window(uri)
            else:
                self.navigate(uri)

    def _on_fullscreen_event(self, this, sender, args):
        if not sender:
            return

        fullscreen = self._get_bool(sender, WV_GET_FULLSCREEN)

        if self.on_fullscreen_changed is not None:
            self.on_fullscreen_changed(fullscreen)

    # ---------- 常用操作 ----------

    def set_hwnd(self, hwnd: int):
        self._hwnd = hwnd

    def set_bounds(self, x: int, y: int, width: int, height: int):
        if not self.controller:
            return

        rect = wintypes.RECT(int(x), int(y), int(width), int(height))
        self.call(self.controller, CTRL_PUT_BOUNDS, HRESULT, (ctypes.POINTER(wintypes.RECT),), ctypes.byref(rect))

    def navigate(self, url: str):
        if not self.webview:
            return

        self.call(self.webview, WV_NAVIGATE, HRESULT, (wintypes.LPCWSTR,), url)

    def reload(self):
        if self.webview:
            self.call(self.webview, WV_RELOAD, HRESULT, ())

    def stop(self):
        if self.webview:
            self.call(self.webview, WV_STOP, HRESULT, ())

    def go_back(self):
        if self.webview:
            self.call(self.webview, WV_GO_BACK, HRESULT, ())

    def go_forward(self):
        if self.webview:
            self.call(self.webview, WV_GO_FORWARD, HRESULT, ())

    def can_go_back(self) -> bool:
        return bool(self.webview) and self._get_bool(self.webview, WV_CAN_GO_BACK)

    def can_go_forward(self) -> bool:
        return bool(self.webview) and self._get_bool(self.webview, WV_CAN_GO_FORWARD)

    def set_visible(self, visible: bool):
        """
        显示/隐藏网页。

        必要性：WebView2 是原生子窗口，永远画在 Qt 的非原生子控件上面；
        而 qfluentwidgets 的对话框（MaskDialogBase）是"子控件 + 蒙层"，
        不隐藏网页的话对话框会被网页盖住 → 看起来像卡死。
        """
        if not self.controller:
            return

        self.call(self.controller, CTRL_PUT_VISIBLE, HRESULT, (wintypes.BOOL,), bool(visible))
    def set_zoom(self, zoom: float):
        if not self.controller:
            return

        zoom = max(0.25, min(3.0, float(zoom)))
        self.call(self.controller, CTRL_PUT_ZOOM, HRESULT, (ctypes.c_double,), zoom)

    def get_zoom(self) -> float:
        if not self.controller:
            return 1.0

        out = ctypes.c_double()
        hr = self.call(self.controller, CTRL_GET_ZOOM, HRESULT, (ctypes.POINTER(ctypes.c_double),), ctypes.byref(out))

        return out.value if hr == S_OK else 1.0

    def run_js(self, expression: str, callback=None):
        """执行一段 JS 表达式；结果按 JSON 解析后回调（表达式里的对象请用 JSON.stringify 包一层）"""
        if not self.webview:
            if callback is not None:
                callback(None)
            return

        script = "JSON.stringify(%s)" % expression

        def on_result(this, hr, raw):
            text = ""

            if hr == S_OK and raw:
                try:
                    text = ctypes.wstring_at(raw)

                except Exception:
                    text = ""

            value = None

            if text:
                try:
                    outer = json.loads(text)
                    value = json.loads(outer) if isinstance(outer, str) else outer

                except Exception:
                    value = None

            if callback is not None:
                callback(value)

        handler = self._keep(ComHandler(IIDS["script_handler"], on_result, middle = "hr"))
        self.call(self.webview, WV_EXECUTE_SCRIPT, HRESULT,
                  (wintypes.LPCWSTR, ctypes.c_void_p), script, handler.pointer)

    def run_js_async(self, script: str):
        """执行一段语句型 JS（不关心返回值），内部包成 JSON.stringify 后忽略结果"""
        if not self.webview:
            return

        handler = self._keep(ComHandler(IIDS["script_handler"], lambda this, hr, raw: None, middle = "hr"))
        self.call(self.webview, WV_EXECUTE_SCRIPT, HRESULT,
                  (wintypes.LPCWSTR, ctypes.c_void_p), "(() => { %s; return 1; })()" % script, handler.pointer)

    def shutdown(self):
        if self.closed:
            return

        self.closed = True

        try:
            if self.controller:
                self.call(self.controller, CTRL_CLOSE, HRESULT, ())

        except Exception:
            pass

        self.controller = 0
        self.webview = 0
        self.env = 0
        self.ready = False
        self._handlers.clear()

    # ---------- 内部 ----------

    def _error(self, message: str):
        logging.getLogger(__name__).error("WebView2：%s", message)

        if self.on_error is not None:
            self.on_error(message)
