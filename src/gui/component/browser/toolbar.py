# -*- coding: utf-8 -*-
"""内嵌浏览器顶部工具栏"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout

from qfluentwidgets import FluentIcon, LineEdit, BodyLabel

from ..widget.button import TransparentToolButton
from util.common.translator import localize


class BrowserToolBar(QWidget):
    def __init__(self, parent = None):
        super().__init__(parent)

        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.back_btn = TransparentToolButton(FluentIcon.LEFT_ARROW, self)
        self.forward_btn = TransparentToolButton(FluentIcon.RIGHT_ARROW, self)
        self.reload_btn = TransparentToolButton(FluentIcon.SYNC, self)
        self.home_btn = TransparentToolButton(FluentIcon.HOME, self)

        for button, tip in (
            (self.back_btn, localize("后退", "上一頁", "Back")),
            (self.forward_btn, localize("前进", "下一頁", "Forward")),
            (self.reload_btn, localize("刷新", "重新整理", "Reload")),
            (self.home_btn, localize("回到 B 站首页", "回到 B 站首頁", "Bilibili home")),
        ):
            button.setToolTip(tip)

        self.address_edit = LineEdit(self)
        self.address_edit.setPlaceholderText(localize("输入网址后回车", "輸入網址後按 Enter", "Enter URL and press Enter"))
        self.address_edit.setClearButtonEnabled(True)

        self.external_btn = TransparentToolButton(FluentIcon.LINK, self)
        self.external_btn.setToolTip(localize("在系统浏览器中打开", "在系統瀏覽器中開啟", "Open in system browser"))

        self.zoom_out_btn = TransparentToolButton(FluentIcon.ZOOM_OUT, self)
        self.zoom_out_btn.setToolTip(localize("缩小网页", "縮小網頁", "Zoom out"))

        self.zoom_label = BodyLabel("100%", self)
        self.zoom_label.setToolTip(localize("点击恢复 100%", "點擊恢復 100%", "Click to reset to 100%"))
        self.zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_label.setFixedWidth(52)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.zoom_in_btn = TransparentToolButton(FluentIcon.ZOOM_IN, self)
        self.zoom_in_btn.setToolTip(localize("放大网页", "放大網頁", "Zoom in"))

        self.back_btn.setEnabled(False)
        self.forward_btn.setEnabled(False)

        layout.addWidget(self.back_btn)
        layout.addWidget(self.forward_btn)
        layout.addWidget(self.reload_btn)
        layout.addWidget(self.home_btn)
        layout.addSpacing(4)
        layout.addWidget(self.address_edit, 1)
        layout.addWidget(self.external_btn)
        layout.addSpacing(8)
        layout.addWidget(self.zoom_out_btn)
        layout.addWidget(self.zoom_label)
        layout.addWidget(self.zoom_in_btn)

    def set_address(self, url: str):
        if not self.address_edit.hasFocus():
            self.address_edit.setText(url)

    def set_zoom_text(self, zoom: float):
        self.zoom_label.setText("%d%%" % round(zoom * 100))

    def set_nav_state(self, can_back: bool, can_forward: bool):
        self.back_btn.setEnabled(can_back)
        self.forward_btn.setEnabled(can_forward)
