# -*- coding: utf-8 -*-
"""
Bili23 Downloader GUI 2.20.0 —— 开发/修改用启动器

用途：
    不修改、不重签 Bili23.exe，直接用官方安装目录里的 Python 3.13 运行时 +
    PySide6/qfluentwidgets 依赖，运行 E:\\Agents_Workspace\\Bili23-GUI-2.20.0\\src
    下这份可编辑源码。

原理：
    官方 exe 是 PyStand 启动器：它把一份 zip（内含 main.py / gui / util / res 的
    .py 与 .pyc）嵌进 exe，启动时注入 PYSTAND_* 环境变量，再用 runtime\\python.exe
    执行内嵌的引导脚本，由自定义 import hook 从内存 zip 里加载模块。
    这里把同样的环境变量和 sys.path 手工补齐，然后按普通 Python 包的方式
    从磁盘源码目录导入 main.py，效果等价于运行打包版。

用法：
    pythonw.exe launcher.py                # 正常启动（跟原版行为一致，单实例锁共用）
    python.exe  launcher.py --smoke        # 只导入模块并打印环境信息，不建窗口
    python.exe  launcher.py --selftest 5   # 启动界面，5 秒后自动退出（回归验证用）

环境变量：
    BILI23_HOME  覆盖安装目录（默认 D:\\Bili23 Downloader）
"""

import os
import sys

DEFAULT_HOME = r"D:\Bili23 Downloader"

HOME = os.environ.get("BILI23_HOME") or DEFAULT_HOME
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")

if not os.path.isdir(SRC):
    raise SystemExit("源码目录不存在：" + SRC)

# --- 复刻 PyStand 引导脚本设置的环境变量 -----------------------------------
os.environ.setdefault("PYSTAND", os.path.join(HOME, "Bili23.exe"))
os.environ.setdefault("PYSTAND_HOME", HOME)
os.environ.setdefault("PYSTAND_RUNTIME", os.path.join(HOME, "runtime"))
os.environ.setdefault("PYSTAND_SCRIPT", os.path.join(SRC, "main.py"))

# --- 复刻 sys.path 结构 -----------------------------------------------------
sys.path.insert(0, SRC)

for sub in (".", "lib", "site-packages", "runtime"):
    p = os.path.abspath(os.path.join(HOME, sub))
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)

_sp = os.path.join(HOME, "site-packages")
for sub in (("win32",), ("win32", "lib"), ("Pythonwin",)):
    p = os.path.join(_sp, *sub)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)

try:
    import pywin32_bootstrap  # noqa: F401  pywin32 初始化，必须在导入 win32* 之前

except ImportError:
    pass

# --- 复刻 PyStand 的其他行为 -------------------------------------------------
os.chdir(HOME)

if not hasattr(sys, "frozen"):
    sys.frozen = True

# 标记这是开发运行（直接跑 src）。main.py 里的外置补丁层据此跳过，
# 否则安装目录的 patch\ 会盖住 src，改源码不生效 / 测的不是源码
sys._bili23_dev_run = True

sys.PYSTAND = os.environ["PYSTAND"]
sys.PYSTAND_HOME = os.environ["PYSTAND_HOME"]
sys.PYSTAND_SCRIPT = os.environ["PYSTAND_SCRIPT"]

MAIN = os.path.join(SRC, "main.py")


def smoke():
    """只导入、不建窗口：检查源码是否可用、依赖版本、ffmpeg 探测结果。"""
    import main  # noqa: F401  执行 main.py 模块级初始化（日志、Qt 消息处理器）

    from PySide6 import __version__ as pyside_version

    import qfluentwidgets

    from util.common.config import config
    from util.ffmpeg import init_ffmpeg
    from util.common.runtime import runtime

    init_ffmpeg()

    print("HOME           =", HOME)
    print("SRC            =", SRC)
    print("python         =", sys.version.split()[0])
    print("PySide6        =", pyside_version)
    print("qfluentwidgets =", getattr(qfluentwidgets, "__version__", "?"))
    print("app_version    =", config.app_version)
    print("download_path  =", config.get(config.download_path))
    print("download_thread=", config.get(config.download_thread))
    print("ffmpeg_source  =", config.get(config.ffmpeg_source))
    print("ffmpeg custom  =", repr(config.get(config.custom_ffmpeg_path)))
    print("ffmpeg exe     =", runtime.ffmpeg.executable)
    print("ffmpeg bundle  =", runtime.ffmpeg.bundle_exist)
    print("ffmpeg unavail =", runtime.ffmpeg.unavailable)
    print("smoke OK")


def selftest(seconds: float, graceful: bool = False):
    """正常启动界面，过 N 秒自动退出，用于确认改动没有把启动链路弄坏。

    默认直接走 main.shutdown_process()（与原版退出时的收尾路径相同，
    TerminateProcess，秒退），适合高频回归；加 --graceful 则走 Qt 的
    QApplication.quit()，能顺带验证事件循环与关闭流程，但实测要等约 30 秒
    才真正退出（程序自身有网络/线程收尾逻辑），不适合反复跑。
    """
    import main as app_main

    from PySide6.QtCore import QTimer

    if graceful:
        original_exec = app_main.Application.exec

        def exec_with_autoclose():
            instance = app_main.Application.instance()
            QTimer.singleShot(int(seconds * 1000), instance.quit)
            return original_exec()

        app_main.Application.exec = staticmethod(exec_with_autoclose)
    else:
        original_exec = app_main.Application.exec

        def exec_with_autoclose():
            QTimer.singleShot(int(seconds * 1000), lambda: app_main.shutdown_process(0))
            return original_exec()

        app_main.Application.exec = staticmethod(exec_with_autoclose)

    print("selftest: 启动界面，%.0f 秒后自动退出%s" % (seconds, "（graceful）" if graceful else ""), flush=True)

    app_main._main()


def main():
    args = sys.argv[1:]

    sys.argv = [MAIN] + args

    if "--smoke" in args:
        smoke()
    elif "--selftest" in args:
        index = args.index("--selftest")
        seconds = float(args[index + 1]) if len(args) > index + 1 else 5.0
        sys.argv = [MAIN]
        selftest(seconds)
    else:
        import runpy

        runpy.run_path(MAIN, run_name="__main__")


if __name__ == "__main__":
    main()
