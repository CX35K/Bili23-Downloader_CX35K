# -*- coding: utf-8 -*-
r"""
把「设置 → 下载 → 下载格式」卡片渲染成 PNG，并检查开关是否被文案顶出可视区域。

默认用 offscreen 平台，不弹窗口；字体通过 QT_QPA_FONTDIR 指向系统字体目录。
    "D:\\Bili23 Downloader\\runtime\\python.exe" tools\\capture_setting_card.py [宽度]

宽度默认 700（主窗口 950 减去导航栏与页边距后的实际可用宽度）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# offscreen 平台不带字体（Qt6 起不再随包分发），不指路的话所有文字都渲染成方框。
# QT_QPA_FONTDIR 是 minimal/offscreen 插件用来装载字体库的入口
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import launcher  # noqa: E402

# 必须赶在创建 QApplication 之前导入：config.py 在导入期用
# QStandardPaths.AppDataLocation 计算配置路径，QApplication 一旦存在，
# 路径会按"应用名=python"多出一层（%APPDATA%\python\...），读到的就不是真实配置
from gui.component.setting.card import DownloadFormatCard  # noqa: E402

from util.common.config import config  # noqa: E402

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from PySide6.QtCore import QTranslator, QPoint  # noqa: E402

OUT = os.path.join(ROOT, "docs", "设置-下载格式-新增M4A转FLAC.png")


def install_translators(app: QApplication):
    """复刻 main.py 的翻译装载，否则 self.tr() 的文案会全部显示英文源文"""
    from qfluentwidgets import FluentTranslator

    import res.resources_rc  # noqa: F401  注册 :/bili23/... 资源

    locale = config.get(config.language).value

    fluent_translator = FluentTranslator(locale)
    bili23_translator = QTranslator()
    bili23_translator.load(locale, "bili23", ".", ":/bili23/i18n")

    app.installTranslator(fluent_translator)
    app.installTranslator(bili23_translator)

    return [fluent_translator, bili23_translator]


def pump(app: QApplication, times: int = 30):
    for _ in range(times):
        app.processEvents()
        time.sleep(0.05)


def check_layout(card: DownloadFormatCard) -> bool:
    """
    检查右侧开关是否落在卡片可视宽度内

    文案是单行 QLabel，变长会把整行撑宽、把右侧开关顶出可视区域。
    断言必须在 grab() 之后跑：控件没 show() 过时布局还没激活，几何位置是
    初始值，直接量会得到无意义的数字
    """
    from qfluentwidgets import SwitchButton

    ok = True

    for button in card.findChildren(SwitchButton):
        top_left = button.mapTo(card, QPoint(0, 0))

        right = top_left.x() + button.width()

        inside = top_left.x() >= 0 and right <= card.width()

        name = getattr(getattr(button, "config_item", None), "key", "?")

        print("    switch %-20s x=%-4d right=%-4d card_width=%-4d -> %s" % (
            name, top_left.x(), right, card.width(), "OK" if inside else "OUT OF RANGE"))

        ok &= inside

    if not ok:
        for label in card.findChildren(QLabel):
            text = label.text()

            if text.startswith(("仅下载", "Only applies to audio")):
                print("      超宽文案：%s" % text[:40])

    return ok


def main():
    width = int(sys.argv[1]) if len(sys.argv) > 1 else 700

    legacy_long = "--legacy-long" in sys.argv

    app = QApplication(sys.argv)

    app.setApplicationName("Bili23 Downloader")
    app.setApplicationDisplayName("Bili23 Downloader")

    translators = install_translators(app)

    card = DownloadFormatCard(None)

    if legacy_long:
        # 复现修复前的长文案，用来确认 layout 断言确实能抓到这个回归
        long_text = "仅适用于下载独立音频流（未勾选视频流）。与“M4A 转 MP3”同时开启时以 FLAC 为准；源为有损 AAC，转 FLAC 不会提升音质且体积会明显变大。"

        for label in card.findChildren(QLabel):
            if label.text().startswith("仅下载"):
                label.setText(long_text)

    card.setExpand(True)

    card.resize(width, card.sizeHint().height())

    pump(app)

    card.resize(width, card.sizeHint().height())

    pump(app, 10)

    print("card width =", card.width(), "height =", card.height(), "| legacy_long =", legacy_long)

    out = OUT if not legacy_long else os.path.join(ROOT, "docs", "_legacy_long_text_preview.png")

    os.makedirs(os.path.dirname(out), exist_ok = True)

    # grab() 会强制走一遍布局，几何位置此时才有效
    pixmap = card.grab()

    layout_ok = check_layout(card)

    pixmap.save(out, "PNG")

    print("saved:", out, pixmap.width(), "x", pixmap.height())
    print("layout:", "OK" if layout_ok else "FAIL")

    del translators

    if legacy_long:
        # 长文案必须被判为 OVERFLOW（退出码 0 表示断言生效）
        print("legacy-long assertion:", "detected" if not layout_ok else "NOT detected")
        sys.exit(0 if not layout_ok else 1)

    sys.exit(0 if layout_ok else 1)


if __name__ == "__main__":
    main()
