"""Graphite / Copper Bench: native Qt presentation, independent of diagnostics."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QProgressBar,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
)

from .models import Health, ResultStatus

TOKENS = {
    "background": "#141917",
    "panel": "#1D2521",
    "readout": "#101512",
    "border": "#465249",
    "text": "#EDF0E9",
    "secondary": "#ADB8AE",
    "accent": "#D7A15D",
    "pass": "#DEE8DC",
    "warning": "#F0BE69",
    "fault": "#ED859C",
    "unavailable": "#A6ADA7",
    "manual": "#B8ABD8",
    "selection": "#394A3D",
    "selection_text": "#FFFFFF",
    "table_header": "#29352D",
    "alternate_row": "#202923",
    "row_hover": "#303C33",
    "progress_fill": "#D7A15D",
}
DISPLAY_FONT = "Barlow Semi Condensed"
MONO_FONT = "Source Code Pro"

STATUS_COLORS = {
    ResultStatus.PASS: TOKENS["pass"],
    ResultStatus.WARNING: TOKENS["warning"],
    ResultStatus.FAIL: TOKENS["fault"],
    ResultStatus.MANUAL: TOKENS["manual"],
    ResultStatus.NOT_AVAILABLE: TOKENS["unavailable"],
    ResultStatus.NOT_TESTED: TOKENS["unavailable"],
}
HEALTH_STATUS = {
    Health.UNKNOWN: ResultStatus.NOT_TESTED,
    Health.GOOD: ResultStatus.PASS,
    Health.WARNING: ResultStatus.WARNING,
    Health.PROBLEM: ResultStatus.FAIL,
}


def mono_font(size: int = 12, bold: bool = False) -> QFont:
    font = QFont(MONO_FONT)
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def paint_marker(painter: QPainter, rect: QRectF, status: ResultStatus) -> None:
    """Use geometry, not font glyphs, so every status survives font/platform changes."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(STATUS_COLORS[status])
    painter.setPen(QPen(color, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r = rect.adjusted(2, 2, -2, -2)
    cx, cy = r.center().x(), r.center().y()
    if status == ResultStatus.PASS:
        painter.setBrush(color)
        painter.drawEllipse(r)
    elif status == ResultStatus.WARNING:
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx, r.top()),
                    QPointF(r.right(), r.bottom()),
                    QPointF(r.left(), r.bottom()),
                ]
            )
        )
    elif status == ResultStatus.NOT_AVAILABLE:
        painter.drawRect(r)
        painter.drawLine(r.bottomLeft(), r.topRight())
    elif status in (ResultStatus.FAIL, ResultStatus.MANUAL):
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx, r.top()),
                    QPointF(r.right(), cy),
                    QPointF(cx, r.bottom()),
                    QPointF(r.left(), cy),
                ]
            )
        )
        if status == ResultStatus.FAIL:
            painter.drawLine(QPointF(cx - 2, cy - 2), QPointF(cx + 2, cy + 2))
            painter.drawLine(QPointF(cx - 2, cy + 2), QPointF(cx + 2, cy - 2))
    else:
        painter.drawEllipse(r)
    painter.restore()


def status_icon(status: ResultStatus) -> QIcon:
    icon = QIcon()
    for scale in (1, 2, 3):
        pixmap = QPixmap(16 * scale, 16 * scale)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        paint_marker(painter, QRectF(0, 0, 16, 16), status)
        painter.end()
        # Retain the shape and status color when Qt selects the row.
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Disabled):
            icon.addPixmap(pixmap, mode)
    return icon


class StatusLabel(QLabel):
    """The existing text label with a painted indicator; no child widget or new action."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.status = ResultStatus.NOT_TESTED
        self.setContentsMargins(23, 0, 0, 0)

    def set_status(self, status: ResultStatus) -> None:
        self.status = status
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor(STATUS_COLORS[status]))
        self.setPalette(palette)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        paint_marker(painter, QRectF(1, (self.height() - 16) / 2, 16, 16), self.status)
        painter.end()


class ResultsDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if index.column() == 0 and option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(
                option.rect.x(),
                option.rect.y(),
                2,
                option.rect.height(),
                QColor(TOKENS["accent"]),
            )


def style_results_table(table: QTableWidget) -> None:
    table.setAlternatingRowColors(True)
    table.setMouseTracking(True)
    table.setIconSize(QSize(16, 16))
    table.setItemDelegate(ResultsDelegate(table))
    table.verticalHeader().setMinimumSectionSize(36)
    table.setColumnWidth(0, 176)
    # Reserve enough room for the longest existing status, including its marker.
    from PySide6.QtGui import QFontMetrics

    metrics = QFontMetrics(mono_font(bold=True))
    table.setColumnWidth(1, metrics.horizontalAdvance(ResultStatus.MANUAL.value) + 74)


class BenchProgressBar(QProgressBar):
    """Keep QProgressBar's range, value, text, accessibility and busy animation."""

    def paintEvent(self, event) -> None:
        if self.minimum() == self.maximum():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(TOKENS["readout"]))
        painter.setPen(QColor(TOKENS["border"]))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        track = self.rect().adjusted(3, 3, -3, -3)
        ratio = max(
            0.0,
            min(
                1.0, (self.value() - self.minimum()) / (self.maximum() - self.minimum())
            ),
        )
        filled = track.adjusted(0, 0, -round(track.width() * (1 - ratio)), 0)
        painter.save()
        painter.setClipRect(filled)
        for x in range(track.left(), track.right() + 1, 9):
            painter.fillRect(
                x, track.top(), 7, track.height(), QColor(TOKENS["progress_fill"])
            )
        painter.restore()
        if self.isTextVisible():
            # A small opaque readout keeps percentage contrast stable over segments.
            text = self.text()
            readout = painter.fontMetrics().boundingRect(text).adjusted(-6, -1, 6, 1)
            readout.moveCenter(self.rect().center())
            painter.fillRect(readout, QColor(TOKENS["readout"]))
            painter.setPen(QColor(TOKENS["text"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


def apply_theme(app: QApplication) -> None:
    if not app.property("benchFontsLoaded"):
        # Byte loading avoids FreeType path encoding failures on Windows.
        for path in sorted((Path(__file__).parent / "assets" / "fonts").glob("*.ttf")):
            if QFontDatabase.addApplicationFontFromData(path.read_bytes()) == -1:
                logging.getLogger(__name__).warning(
                    "Could not load bundled font: %s", path.name
                )
        app.setProperty("benchFontsLoaded", True)
    app.setStyle("Fusion")
    font = QFont(DISPLAY_FONT)
    font.setPixelSize(14)
    app.setFont(font)
    palette = QPalette()
    for role, token in {
        "Window": "background",
        "WindowText": "text",
        "Base": "readout",
        "AlternateBase": "alternate_row",
        "Text": "text",
        "Button": "panel",
        "ButtonText": "text",
        "Highlight": "selection",
        "HighlightedText": "selection_text",
        "ToolTipBase": "table_header",
        "ToolTipText": "text",
        "PlaceholderText": "secondary",
        "Light": "border",
        "Mid": "border",
        "Dark": "readout",
        "Shadow": "readout",
        "Link": "accent",
    }.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(TOKENS[token]))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(
            QPalette.ColorGroup.Disabled, role, QColor(TOKENS["unavailable"])
        )
    app.setPalette(palette)
    t = TOKENS
    app.setStyleSheet(f"""
        QWidget {{ font-family: '{DISPLAY_FONT}'; font-size: 14px; }}
        QWidget#central, QDialog {{ background: {t["background"]}; }}
        QLabel#title {{ font-size: 32px; font-weight: 600; }}
        QLabel#subtitle {{ color: {t["secondary"]}; font-size: 15px; }}
        QLabel#healthLabel {{ color: {t["secondary"]}; font-size: 14px; font-weight: 400; }}
        QLabel#healthValue {{ font-family: '{MONO_FONT}'; font-size: 18px; font-weight: 600; }}
        QFrame#infoFrame, QFrame#detailFrame {{ background: {t["panel"]}; border: 1px solid {t["border"]}; border-radius: 0; }}
        QLabel#infoLabel {{ color: {t["secondary"]}; font-size: 14px; }}
        QLabel#infoValue {{ font-family: '{MONO_FONT}'; font-size: 12px; }}
        QLabel#sectionTitle, QLabel#dialogTitle {{ font-size: 20px; font-weight: 600; padding-bottom: 6px; border-bottom: 1px solid {t["border"]}; }}
        QLabel#detailStatus {{ font-family: '{MONO_FONT}'; font-size: 13px; font-weight: 600; padding-top: 4px; padding-bottom: 4px; }}
        QLabel#detailSummary {{ font-size: 15px; }}
        QLabel#progressLabel {{ color: {t["secondary"]}; font-size: 14px; }}
        QPushButton {{ background: {t["panel"]}; border: 1px solid {t["border"]}; border-radius: 2px; color: {t["text"]}; font-weight: 600; min-height: 28px; padding: 4px 10px; }}
        QPushButton:hover {{ background: {t["row_hover"]}; border-color: {t["accent"]}; }}
        QPushButton:pressed {{ background: {t["readout"]}; border-color: {t["accent"]}; }}
        QPushButton:focus {{ border: 2px solid {t["accent"]}; padding: 3px 9px; }}
        QPushButton[primary='true'] {{ background: {t["accent"]}; border-color: {t["accent"]}; color: {t["readout"]}; }}
        QPushButton[primary='true']:hover {{ background: {t["warning"]}; border-color: {t["warning"]}; }}
        QPushButton[primary='true']:pressed {{ background: {t["warning"]}; border-color: {t["readout"]}; }}
        QPushButton[primary='true']:focus {{ border-color: {t["text"]}; }}
        QPushButton:disabled, QPushButton[primary='true']:disabled {{ background: {t["background"]}; border-color: {t["border"]}; color: {t["unavailable"]}; }}
        QTableWidget {{ font-family: '{MONO_FONT}'; font-size: 12px; background: {t["panel"]}; alternate-background-color: {t["alternate_row"]}; border: 1px solid {t["border"]}; border-radius: 0; gridline-color: {t["table_header"]}; selection-background-color: {t["selection"]}; selection-color: {t["selection_text"]}; }}
        QTableWidget::item {{ padding: 7px 8px; }}
        QTableWidget::item:hover {{ background: {t["row_hover"]}; }}
        QTableWidget::item:selected {{ background: {t["selection"]}; color: {t["selection_text"]}; }}
        QTableWidget:focus {{ border-color: {t["accent"]}; }}
        QHeaderView::section {{ background: {t["table_header"]}; color: {t["text"]}; font-family: '{DISPLAY_FONT}'; font-size: 14px; font-weight: 600; border: none; border-right: 1px solid {t["border"]}; border-bottom: 1px solid {t["border"]}; padding: 8px; }}
        QTableCornerButton::section {{ background: {t["table_header"]}; border: none; }}
        QPlainTextEdit {{ placeholder-text-color: {t['secondary']}; font-family: '{MONO_FONT}'; font-size: 12px; background: {t["readout"]}; border: 1px solid {t["border"]}; border-radius: 0; color: {t["text"]}; padding: 10px; selection-background-color: {t["selection"]}; selection-color: {t["selection_text"]}; }}
        QPlainTextEdit:focus {{ border-color: {t["accent"]}; }}
        QProgressBar {{ font-family: '{MONO_FONT}'; font-size: 12px; background: {t["readout"]}; border: 1px solid {t["border"]}; border-radius: 0; min-height: 24px; text-align: center; color: {t["text"]}; }}
        QProgressBar::chunk {{ background: {t["progress_fill"]}; width: 7px; margin: 2px 2px 2px 0; }}
        QSplitter::handle {{ background: {t["background"]}; width: 8px; }}
        QSplitter::handle:hover {{ background: {t["border"]}; }}
        QScrollArea {{ border: 1px solid {t["border"]}; }}
        QToolTip {{ background: {t["table_header"]}; color: {t["text"]}; border: 1px solid {t["border"]}; padding: 5px; }}
    """)
