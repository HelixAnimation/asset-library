from qtpy.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QPushButton, QSizePolicy,
)
from qtpy.QtCore import Qt, Signal

from ui.styles import (
    BG_PRIMARY, BG_SECONDARY, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_LIGHT, BORDER_MID,
)


class TagDropdown(QFrame):
    """Autocomplete popup — works as a floating tool window or an in-dialog overlay.

    overlay=False (default): top-level Qt.Tool window (used in the main search bar).
    overlay=True: regular child widget positioned absolutely inside the parent dialog
                  via raise_() — avoids all modal-dialog window-manager issues.
    """

    tagSelected  = Signal(str)
    nameSelected = Signal(str)

    _BTN_H = 28

    def __init__(self, parent=None, overlay=False):
        if overlay:
            super().__init__(parent)
        else:
            super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setObjectName("tagDropdown")
        self.setStyleSheet(
            "#tagDropdown {"
            "  background: %s; border: 1px solid %s; border-radius: 6px;"
            "  padding: 4px 0;"
            "}" % (BG_PRIMARY, BORDER_MID)
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(0)
        self._btns = []
        self._sel  = -1

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._btns = []
        self._sel  = -1

    def _addHeader(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: %s; font-size: 10px; font-family: 'IBM Plex Mono', monospace;"
            " letter-spacing: 1px; padding: 4px 12px 2px; background: transparent;"
            % TEXT_TERTIARY
        )
        self._layout.addWidget(lbl)

    def _addBtn(self, label, signal, arg, icon_prefix=""):
        btn = QPushButton(icon_prefix + label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(self._BTN_H)
        self._applyBtnStyle(btn, selected=False)
        btn.clicked.connect(lambda _, a=arg: signal.emit(a))
        self._layout.addWidget(btn)
        self._btns.append((signal, arg, btn))

    def _applyBtnStyle(self, btn, selected):
        if selected:
            btn.setStyleSheet(
                "QPushButton {"
                "  background: %s; border: none; color: %s;"
                "  font-size: 12px; font-family: 'IBM Plex Sans', sans-serif;"
                "  padding: 0 12px; text-align: left;"
                "}" % (BG_SECONDARY, TEXT_PRIMARY)
            )
        else:
            btn.setStyleSheet(
                "QPushButton {"
                "  background: transparent; border: none; color: %s;"
                "  font-size: 12px; font-family: 'IBM Plex Sans', sans-serif;"
                "  padding: 0 12px; text-align: left;"
                "}"
                "QPushButton:hover { background: %s; color: %s; }"
                % (TEXT_SECONDARY, BG_SECONDARY, TEXT_PRIMARY)
            )

    def selectNext(self):
        if self._btns:
            self._highlight(min(self._sel + 1, len(self._btns) - 1))

    def selectPrev(self):
        if self._btns:
            self._highlight(max(self._sel - 1, -1))

    def _highlight(self, idx):
        if 0 <= self._sel < len(self._btns):
            self._applyBtnStyle(self._btns[self._sel][2], selected=False)
        self._sel = idx
        if 0 <= self._sel < len(self._btns):
            self._applyBtnStyle(self._btns[self._sel][2], selected=True)

    def activateSelected(self):
        if 0 <= self._sel < len(self._btns):
            signal, arg, _ = self._btns[self._sel]
            signal.emit(arg)
            return True
        return False

    def setItems(self, tags, asset_names=None):
        self._clear()
        asset_names = asset_names or []
        row_count = 0

        if tags:
            self._addHeader("TAGS")
            row_count += 1
            for t in tags:
                self._addBtn(t, self.tagSelected, t, "# ")
                row_count += 1

        if asset_names:
            if tags:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setFixedHeight(1)
                sep.setStyleSheet(
                    "background: %s; border: none; margin: 4px 12px;" % BORDER_LIGHT
                )
                self._layout.addWidget(sep)
                row_count += 1
            self._addHeader("ASSETS")
            row_count += 1
            for n in asset_names:
                self._addBtn(n, self.nameSelected, n)
                row_count += 1

        self.setFixedWidth(260)
        self.setFixedHeight(min(row_count * self._BTN_H + 16, 300))
