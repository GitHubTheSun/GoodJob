"""可拖动的 GoodJob。靠到屏幕边缘会吸附，移开后收回。"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import (
    QAbstractAnimation,
    QDate,
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Signal,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QTextLayout,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDateTimeEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from goodjob.i18n import tr
from goodjob.parse import extract_items, format_when
from goodjob.snap import HIDE_DELAY, PEEK, Box, placed, snap_edge, want_open
from goodjob.speech import ListenWorker
from goodjob.store import PRIORITY_HIGH, PRIORITY_LOW, PRIORITY_MID, PRIORITY_PLUS, Store, Task, load_config, save_config
from goodjob.themes import Theme, stylesheet, theme_by_id

PANEL_WIDTH = 360
PANEL_HEIGHT = 640
CORNER = 18
OPEN = "open"
CLOSED = "closed"
_DAY_KEYS = ("today", "tomorrow", "day_after", "later")


def screen_key(screen) -> str:
    geo = screen.geometry()
    return f"{geo.x()},{geo.y()},{geo.width()}x{geo.height()}"


def panel_path(width: int, height: int, edge: str | None) -> QPainterPath:
    tl = tr = bl = br = True
    if edge == "right":
        tr = br = False
    elif edge == "left":
        tl = bl = False
    elif edge == "top":
        tl = tr = False
    path = QPainterPath()
    radius = float(CORNER)
    w = float(width)
    h = float(height)
    path.moveTo(radius if tl else 0, 0)
    path.lineTo(w - (radius if tr else 0), 0)
    if tr:
        path.arcTo(w - 2 * radius, 0, 2 * radius, 2 * radius, 90, -90)
    else:
        path.lineTo(w, 0)
    path.lineTo(w, h - (radius if br else 0))
    if br:
        path.arcTo(w - 2 * radius, h - 2 * radius, 2 * radius, 2 * radius, 0, -90)
    else:
        path.lineTo(w, h)
    path.lineTo(radius if bl else 0, h)
    if bl:
        path.arcTo(0, h - 2 * radius, 2 * radius, 2 * radius, 270, -90)
    else:
        path.lineTo(0, h)
    path.lineTo(0, radius if tl else 0)
    if tl:
        path.arcTo(0, 0, 2 * radius, 2 * radius, 180, -90)
    else:
        path.lineTo(0, 0)
    path.closeSubpath()
    return path


def make_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#e2a33a"))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(QColor("#1a1408"))
    painter.setFont(QFont("Microsoft YaHei UI", 26, QFont.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "G")
    painter.end()
    return QIcon(pixmap)


class CheckDot(QPushButton):
    def __init__(self, accent: str, ink: str, muted: str) -> None:
        super().__init__()
        self._accent = QColor(accent)
        self._ink = QColor(ink)
        self._muted = QColor(muted)
        self.setCheckable(True)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = self.rect().adjusted(2, 2, -2, -2)
        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._accent)
            painter.drawRoundedRect(box, 5, 5)
            pen = QPen(self._ink, 2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(box.left() + 4, box.center().y(), box.left() + 7, box.bottom() - 4)
            painter.drawLine(box.left() + 7, box.bottom() - 4, box.right() - 3, box.top() + 4)
        else:
            painter.setPen(QPen(self._muted, 1.4))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(box, 5, 5)
        painter.end()


class FitTitle(QLabel):
    """优先一行放下；放不下就缩小字号，折成最多两行。点一下可以修改。"""

    clicked = Signal()

    def __init__(self, text: str, color: str, strike: bool = False) -> None:
        super().__init__()
        self._full = text
        self._color = color
        self._strike = strike
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setCursor(Qt.PointingHandCursor)
        self._apply(14, text, one_line=True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:
        self._fit()
        super().resizeEvent(event)

    def showEvent(self, event) -> None:
        self._fit()
        super().showEvent(event)

    def _fit(self) -> None:
        if getattr(self, "_fitting", False):
            return
        width = max(0, self.contentsRect().width())
        if width < 8:
            return
        self._fitting = True
        try:
            if QFontMetrics(self._font(14)).horizontalAdvance(self._full) <= width:
                self._apply(14, self._full, one_line=True)
                return
            small = self._font(12)
            self._apply(12, _wrap_lines(self._full, small, width, 2), one_line=False)
        finally:
            self._fitting = False

    def _font(self, pixels: int) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(pixels)
        font.setStrikeOut(self._strike)
        return font

    def _apply(self, pixels: int, text: str, one_line: bool) -> None:
        font = self._font(pixels)
        self.setFont(font)
        self.setText(text)
        self.setWordWrap(not one_line)
        line_count = 1 if one_line else max(1, text.count("\n") + 1)
        self.setFixedHeight(QFontMetrics(font).height() * line_count + 2)
        self.setStyleSheet(f"color: {self._color}; background: transparent;")

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(48, max(22, self.height()))

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(0, 20)


class MicButton(QPushButton):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self._listening = False
        self._accent = QColor("#e2a33a")
        self._ink = QColor("#1a1408")
        self._muted = QColor("#8b919c")
        self._line = QColor("#3a4050")

    def set_colors(self, accent: str, ink: str, muted: str, line: str) -> None:
        self._accent = QColor(accent)
        self._ink = QColor(ink)
        self._muted = QColor(muted)
        self._line = QColor(line)
        self.update()

    def set_listening(self, listening: bool) -> None:
        self._listening = listening
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self._accent if self._listening else self._line, 1.4))
        painter.setBrush(self._accent if self._listening else Qt.NoBrush)
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        color = self._ink if self._listening else self._accent
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(15, 8, 6, 12, 3, 3)
        painter.setPen(QPen(color, 1.6))
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(11, 12, 14, 12, 200 * 16, 140 * 16)
        painter.drawLine(18, 24, 18, 28)
        painter.drawLine(14, 28, 22, 28)
        painter.end()


class DockWindow(QWidget):
    def __init__(self, store: Store | None = None) -> None:
        super().__init__()
        self.store = store or Store()
        self.config = load_config()
        self._shut = False
        self._lang = self.config.get("language") if self.config.get("language") in ("zh", "en") else "zh"
        self._theme_id = self.config.get("theme") if self.config.get("theme") in ("ink", "paper", "forest", "dusk") else "ink"
        self._stt_key = self.config.get("groq_key") if isinstance(self.config.get("groq_key"), str) else ""
        edge = self.config.get("edge", "right")
        self._edge = edge if edge in ("left", "right", "top") else None
        self._ax = self.config.get("x") if isinstance(self.config.get("x"), int) else None
        self._ay = self.config.get("y") if isinstance(self.config.get("y"), int) else None
        self._screen_key = self.config.get("screen") or ""
        self._pinned = bool(self.config.get("pinned", False))
        self._show_done = bool(self.config["done_open"]) if "done_open" in self.config else True
        self._sliding = False
        self._pending_reload = False
        self._page: QWidget | None = None
        self._popup_held = False
        self._day = 0
        self._mode = OPEN
        self._holds = 0
        self._suppress = False
        self._dragging = False
        self._listening = False
        self._draft_remind: datetime | None = None
        self._picked_date = datetime.now().date()
        self._priority = PRIORITY_MID
        self._status = ""
        self._status_until = 0.0
        self._grace_until = 0.0 if self._edge is None or self._pinned else _now() + 3.0
        self._outside_at: float | None = None
        self.theme: Theme = theme_by_id(self._theme_id)

        self.setWindowTitle("GoodJob")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowIcon(make_icon())
        self._build()
        self.listener = ListenWorker()
        self.listener.finished.connect(self._on_speech)
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self._apply_theme()
        self._sync_size()
        self.move(self._target_pos())
        self._apply_texts()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._remind_timer = QTimer(self)
        self._remind_timer.timeout.connect(self._check_reminders)

    def start(self) -> None:
        self.show()
        self.raise_()
        self._timer.start(60)
        self._remind_timer.start(1000)
        QTimer.singleShot(500, self._check_reminders)

    def shutdown(self) -> None:
        if self._shut:
            return
        self._shut = True
        if hasattr(self, "_timer"):
            self._timer.stop()
            self._remind_timer.stop()
        if hasattr(self, "tray"):
            self.tray.hide()
        self._save()
        self.store.close()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 14, 12)
        root.setSpacing(8)

        self._header = QWidget()
        header = QHBoxLayout(self._header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        self.name_label = QLabel("GoodJob")
        self.name_label.setObjectName("appName")
        header.addWidget(self.name_label, 1)
        self.lang_btn = QPushButton()
        self.lang_btn.setObjectName("tiny")
        self.lang_btn.setCursor(Qt.PointingHandCursor)
        self.lang_btn.clicked.connect(self._toggle_lang)
        header.addWidget(self.lang_btn)
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("tiny")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self._toggle_settings)
        header.addWidget(self.settings_btn)
        self.pin_btn = QPushButton()
        self.pin_btn.setObjectName("pin")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setCursor(Qt.PointingHandCursor)
        self.pin_btn.blockSignals(True)
        self.pin_btn.setChecked(self._pinned)
        self.pin_btn.blockSignals(False)
        self.pin_btn.toggled.connect(self._toggle_pin)
        header.addWidget(self.pin_btn)
        self.collapse_btn = QPushButton()
        self.collapse_btn.setObjectName("ghost")
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.clicked.connect(self._collapse)
        header.addWidget(self.collapse_btn)
        self.quit_btn = QPushButton("×")
        self.quit_btn.setFixedSize(28, 28)
        self.quit_btn.setCursor(Qt.PointingHandCursor)
        self.quit_btn.clicked.connect(self._quit)
        header.addWidget(self.quit_btn)
        root.addWidget(self._header)
        self._header.installEventFilter(self)
        self.name_label.installEventFilter(self)
        self._build_settings_popup()

        entry = QHBoxLayout()
        entry.setSpacing(8)
        self.input = QLineEdit()
        self.input.returnPressed.connect(self._add_from_composer)
        entry.addWidget(self.input, 1)
        self.talk_btn = MicButton()
        self.talk_btn.clicked.connect(self._talk)
        entry.addWidget(self.talk_btn)
        root.addLayout(entry)

        self._chips = QHBoxLayout()
        self._chips.setSpacing(6)
        root.addLayout(self._chips)

        clock = QHBoxLayout()
        clock.setSpacing(8)
        self._time_slider = QSlider(Qt.Horizontal)
        self._time_slider.setRange(0, 24 * 4 - 1)
        self._time_slider.valueChanged.connect(self._on_time_slider)
        clock.addWidget(self._time_slider, 1)
        self._time_readout = QLabel("09:00")
        self._time_readout.setObjectName("dayCaption")
        self._time_readout.setFixedWidth(52)
        clock.addWidget(self._time_readout)
        self._date_btn = QPushButton()
        self._date_btn.setObjectName("ghost")
        self._date_btn.setCursor(Qt.PointingHandCursor)
        self._date_btn.clicked.connect(self._open_calendar)
        clock.addWidget(self._date_btn)
        root.addLayout(clock)

        rank = QHBoxLayout()
        rank.setSpacing(6)
        self._priority_buttons: dict[int, QPushButton] = {}
        for value in (PRIORITY_HIGH, PRIORITY_PLUS, PRIORITY_MID, PRIORITY_LOW):
            button = QPushButton()
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _checked=False, chosen=value: self._set_composer_priority(chosen))
            rank.addWidget(button)
            self._priority_buttons[value] = button
        root.addLayout(rank)

        self.add_btn = QPushButton()
        self.add_btn.setObjectName("primary")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setMinimumHeight(44)
        self.add_btn.clicked.connect(self._add_from_composer)
        root.addWidget(self.add_btn)

        self.preview = QLabel()
        self.preview.setObjectName("hint")
        self.preview.setWordWrap(True)
        self.preview.setVisible(False)
        root.addWidget(self.preview)
        self._apply_clock(datetime.now())

        line = QFrame()
        line.setObjectName("rule")
        line.setFrameShape(QFrame.HLine)
        root.addWidget(line)

        self._stage = QWidget()
        self._stage.setMinimumHeight(180)
        self._stage.installEventFilter(self)
        self._prev_btn = QPushButton("‹", self._stage)
        self._next_btn = QPushButton("›", self._stage)
        for button, step in ((self._prev_btn, -1), (self._next_btn, 1)):
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, delta=step: self._slide_day(delta))
        root.addWidget(self._stage, 1)

        self.footer = QLabel()
        self.footer.setVisible(False)

    def _build_settings_popup(self) -> None:
        self._popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        self._popup.setObjectName("settings")
        layout = QVBoxLayout(self._popup)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        self.theme_label = QLabel()
        self.theme_label.setObjectName("setLabel")
        layout.addWidget(self.theme_label)
        themes = QHBoxLayout()
        themes.setSpacing(6)
        self._theme_buttons: dict[str, QPushButton] = {}
        for theme_id in ("ink", "paper", "forest", "dusk"):
            button = QPushButton()
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, chosen=theme_id: self._set_theme(chosen))
            themes.addWidget(button)
            self._theme_buttons[theme_id] = button
        layout.addLayout(themes)
        self.key_label = QLabel()
        self.key_label.setObjectName("setLabel")
        layout.addWidget(self.key_label)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setText(self._stt_key)
        self.key_edit.editingFinished.connect(self._save_key)
        layout.addWidget(self.key_edit)
        self.about_label = QLabel()
        self.about_label.setObjectName("setLabel")
        layout.addWidget(self.about_label)
        self.about_body = QLabel()
        self.about_body.setObjectName("hint")
        self.about_body.setWordWrap(True)
        self.about_body.setFixedWidth(280)
        layout.addWidget(self.about_body)
        self._popup.installEventFilter(self)

    def _apply_theme(self) -> None:
        self.theme = theme_by_id(self._theme_id)
        self.setStyleSheet(stylesheet(self.theme))
        self.setWindowOpacity(1)
        self._popup.setStyleSheet(stylesheet(self.theme))
        self.talk_btn.set_colors(self.theme.accent, self.theme.accent_text, self.theme.muted, self.theme.line)
        self._style_quit()
        self._paint_priority()
        self._paint_choices()
        self._style_arrows()
        self.update()

    def _apply_texts(self) -> None:
        self.lang_btn.setText("EN" if self._lang == "zh" else "中文")
        self.pin_btn.setText(tr(self._lang, "pinned" if self._pinned else "pin"))
        self.collapse_btn.setText(tr(self._lang, "collapse"))
        self.settings_btn.setText(tr(self._lang, "settings"))
        self.theme_label.setText(tr(self._lang, "theme"))
        self.key_label.setText(tr(self._lang, "stt_key"))
        self.key_edit.setPlaceholderText(tr(self._lang, "stt_placeholder"))
        self.about_label.setText(tr(self._lang, "about"))
        self.about_body.setText(tr(self._lang, "about_body"))
        for theme_id, button in self._theme_buttons.items():
            button.setText(tr(self._lang, f"style_{theme_id}"))
        self.input.setPlaceholderText(tr(self._lang, "placeholder"))
        self.add_btn.setText(tr(self._lang, "add"))
        self._fill_chips()
        self._refresh_date_button()
        self._paint_priority()
        self._paint_choices()
        self._rebuild_tray()
        self.reload()

    def _paint_choices(self) -> None:
        for theme_id, button in self._theme_buttons.items():
            button.setStyleSheet(self._choice_style(theme_id == self._theme_id))

    def _style_arrows(self) -> None:
        theme = self.theme
        style = (
            f"QPushButton {{ background: {theme.bg}; color: {theme.text}; border: 1px solid {theme.line}; "
            f"border-radius: 8px; font-size: 16px; font-weight: 700; padding: 0px; }}"
            f"QPushButton:disabled {{ color: {theme.line}; background: {theme.chip}; }}"
        )
        self._prev_btn.setStyleSheet(style)
        self._next_btn.setStyleSheet(style)

    def _style_quit(self) -> None:
        theme = self.theme
        self.quit_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.danger}; "
            f"border: 1.5px solid {theme.danger}; border-radius: 14px; font-size: 14px; padding: 0; }}"
            f"QPushButton:hover {{ background: {theme.danger}; color: {theme.bg}; }}"
        )

    def _choice_style(self, selected: bool) -> str:
        theme = self.theme
        if selected:
            return (
                f"background: {theme.accent}; color: {theme.accent_text}; border: none; "
                "border-radius: 8px; padding: 4px 6px; font-weight: 700;"
            )
        return (
            f"background: {theme.chip}; color: {theme.text}; border: none; "
            "border-radius: 8px; padding: 4px 6px;"
        )

    def _fill_chips(self) -> None:
        _clear_layout(self._chips)
        for key, minutes in (("quick_15", 15), ("quick_1", 60), ("quick_2", 120), ("quick_4", 240)):
            button = QPushButton(tr(self._lang, key))
            button.setObjectName("chip")
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _checked=False, amount=minutes: self._apply_quick(amount))
            self._chips.addWidget(button)

    def _rebuild_tray(self) -> None:
        menu = QMenu()
        menu.addAction(tr(self._lang, "open"), self._open_from_user)
        menu.addAction(tr(self._lang, "quit"), self._quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("GoodJob")

    def reload(self) -> None:
        if self._sliding:
            self._pending_reload = True
            return
        last = self._last_day()
        if self._day > last:
            self._day = last
        page = self._make_day_page()
        page.setParent(self._stage)
        page.show()
        old = self._page
        self._page = page
        if old is not None:
            old.deleteLater()
        self._layout_stage()
        self._refresh_footer(self.store.list_tasks(), datetime.now().replace(second=0, microsecond=0))
        self._refresh_preview()

    def _last_day(self) -> int:
        today = datetime.now().date()
        if any(_bucket(task, today) == 3 for task in self.store.list_tasks()):
            return 3
        return 2

    def _date_text(self) -> str:
        today = datetime.now().date()
        word = tr(self._lang, _DAY_KEYS[self._day] if self._day < 3 else "later")
        if self._day >= 3:
            return word
        day = today + timedelta(days=self._day)
        if self._lang == "zh":
            return f"{day.month}月{day.day}日    {word}"
        return f"{day:%b %d}    {word}"

    def _make_day_page(self) -> QWidget:
        now = datetime.now().replace(second=0, microsecond=0)
        today = now.date()
        tasks = self.store.list_tasks()
        chosen = [task for task in tasks if _bucket(task, today) == self._day]
        open_tasks = sorted((task for task in chosen if not task.done), key=lambda task: _open_sort(task, now))
        done_tasks = [task for task in chosen if task.done]
        theme = self.theme
        page = QWidget()
        page.setObjectName("dayCard")
        page.setStyleSheet(f"QWidget#dayCard {{ background: {theme.card}; border-radius: 16px; }}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 14, 40, 12)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel(self._summary_text(len(open_tasks), len(done_tasks)))
        title.setObjectName("dayCaption")
        title.setStyleSheet(f"color: {theme.text}; background: transparent; font-size: 15px; font-weight: 700;")
        head.addWidget(title, 1)
        if self._day == 0:
            waiting = self._yesterday_open()
            if waiting:
                sync = QPushButton(tr(self._lang, "sync_yesterday", n=waiting))
                sync.setObjectName("chip")
                sync.setCursor(Qt.PointingHandCursor)
                sync.clicked.connect(self._sync_yesterday)
                head.addWidget(sync)
        layout.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(2)
        if not open_tasks and not done_tasks:
            empty = QLabel(tr(self._lang, "empty_day"))
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {theme.muted}; background: transparent;")
            host_layout.addWidget(empty)
        for task in open_tasks:
            host_layout.addWidget(self._task_row(task, theme, done=False))
        if open_tasks and done_tasks:
            gap = QWidget()
            gap.setFixedHeight(10)
            host_layout.addWidget(gap)
        for task in done_tasks:
            host_layout.addWidget(self._task_row(task, theme, done=True))
        host_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)
        return page

    def _layout_stage(self) -> None:
        width = max(1, self._stage.width())
        height = max(1, self._stage.height())
        arrow_h = max(96, height - 28)
        arrow_y = max(8, (height - arrow_h) // 2)
        self._prev_btn.setGeometry(2, arrow_y, 16, arrow_h)
        self._next_btn.setGeometry(max(18, width - 18), arrow_y, 16, arrow_h)
        self._prev_btn.raise_()
        self._next_btn.raise_()
        last = self._last_day()
        self._prev_btn.setEnabled(self._day > 0 and not self._sliding)
        self._next_btn.setEnabled(self._day < last and not self._sliding)
        if not self._sliding and self._page is not None:
            self._page.setGeometry(0, 0, width, height)
            self._page.raise_()
            self._prev_btn.raise_()
            self._next_btn.raise_()

    def _slide_day(self, step: int) -> None:
        if self._sliding or step == 0:
            return
        target = self._day + step
        if target < 0 or target > self._last_day():
            return
        self._sliding = True
        self._day = target
        width = max(1, self._stage.width())
        height = max(1, self._stage.height())
        old = self._page
        new = self._make_day_page()
        new.setParent(self._stage)
        new.setGeometry(step * width, 0, width, height)
        new.show()
        self._prev_btn.raise_()
        self._next_btn.raise_()
        self._prev_btn.setEnabled(False)
        self._next_btn.setEnabled(False)
        if old is None:
            new.setGeometry(0, 0, width, height)
            self._page = new
            self._sliding = False
            self._layout_stage()
            return
        outgoing = QPropertyAnimation(old, b"pos", self)
        outgoing.setDuration(240)
        outgoing.setEasingCurve(QEasingCurve.OutCubic)
        outgoing.setStartValue(old.pos())
        outgoing.setEndValue(QPoint(-step * width, 0))
        incoming = QPropertyAnimation(new, b"pos", self)
        incoming.setDuration(240)
        incoming.setEasingCurve(QEasingCurve.OutCubic)
        incoming.setStartValue(QPoint(step * width, 0))
        incoming.setEndValue(QPoint(0, 0))
        group = QParallelAnimationGroup(self)
        group.addAnimation(outgoing)
        group.addAnimation(incoming)

        def finished() -> None:
            old.deleteLater()
            self._page = new
            self._sliding = False
            self._layout_stage()
            self._refresh_footer(self.store.list_tasks(), datetime.now().replace(second=0, microsecond=0))
            if self._pending_reload:
                self._pending_reload = False
                self.reload()

        group.finished.connect(finished)
        self._slide_group = group
        group.start()

    def _summary_text(self, open_count: int, done_count: int) -> str:
        today = datetime.now().date()
        if self._day >= 3:
            word = tr(self._lang, "later")
            date = ""
        else:
            day = today + timedelta(days=self._day)
            word = tr(self._lang, _DAY_KEYS[self._day])
            date = f"{day.month}月{day.day}日" if self._lang == "zh" else f"{day:%b %d}"
        return tr(self._lang, "summary", date=date, word=word, open=open_count, done=done_count)

    def _yesterday_open(self) -> int:
        yesterday = datetime.now().date() - timedelta(days=1)
        count = 0
        for task in self.store.list_tasks():
            if task.done:
                continue
            if task.remind_at is not None and task.remind_at.date() == yesterday:
                count += 1
            elif task.remind_at is None and task.created_at.date() == yesterday:
                count += 1
        return count

    def _sync_yesterday(self) -> None:
        self.store.carry_yesterday(datetime.now())
        self._day = 0
        self.reload()

    def _task_row(self, task: Task, theme: Theme, done: bool) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(6)
        check = CheckDot(theme.accent, theme.accent_text, theme.muted)
        check.setChecked(done)
        check.clicked.connect(lambda _checked=False, box=check, task_id=task.id: self._set_done(task_id, box.isChecked()))
        layout.addWidget(check)
        when = QLabel(f"{task.remind_at:%H:%M}" if task.remind_at else "—")
        when.setFixedWidth(44)
        when.setStyleSheet(f"color: {theme.muted if done else theme.accent}; background: transparent; font-size: 13px;")
        layout.addWidget(when)
        if not done:
            rank = QPushButton(_priority_label(self._lang, task.priority))
            rank.setCursor(Qt.PointingHandCursor)
            rank.setFixedHeight(18)
            rank.setStyleSheet(self._row_priority_style(task.priority))
            rank.clicked.connect(lambda _checked=False, task_id=task.id, current=task.priority: self._cycle_priority(task_id, current))
            layout.addWidget(rank)
        title = FitTitle(task.title, theme.muted if done else theme.text, strike=done)
        title.clicked.connect(lambda task_id=task.id: self._edit_task(task_id))
        layout.addWidget(title, 1)
        remove = QPushButton("×")
        remove.setObjectName("dangerIcon")
        remove.setFixedSize(16, 16)
        remove.setCursor(Qt.PointingHandCursor)
        remove.clicked.connect(lambda _checked=False, task_id=task.id: self._delete(task_id))
        layout.addWidget(remove)
        return row

    def _refresh_footer(self, tasks: list[Task], now: datetime) -> None:
        return

    def _refresh_preview(self) -> None:
        if self._listening:
            text = tr(self._lang, "listening")
            hot = True
        elif self._status and _now() < self._status_until:
            text = self._status
            hot = False
        else:
            self.preview.clear()
            self.preview.setVisible(False)
            return
        color = self.theme.accent if hot else self.theme.muted
        self.preview.setVisible(True)
        self.preview.setText(text)
        self.preview.setStyleSheet(f"color: {color}; font-size: 12px; background: transparent;")

    def _preview_for(self, items: list[tuple[str, datetime | None]]) -> tuple[str, bool]:
        now = datetime.now()
        if not items:
            return tr(self._lang, "example"), False
        if len(items) == 1 and items[0][1] is not None:
            return tr(self._lang, "will_one", title=items[0][0], when=format_when(items[0][1], now, self._lang)), True
        if len(items) == 1:
            return tr(self._lang, "will_note", title=items[0][0]), False
        return tr(self._lang, "will_many", n=len(items), brief=self._brief(items, now)), True

    def _brief(self, items: list[tuple[str, datetime | None]], now: datetime) -> str:
        parts: list[str] = []
        for title, when in items[:3]:
            if when is None:
                parts.append(title)
            elif self._lang == "zh":
                parts.append(f"{title}（{format_when(when, now, self._lang)}）")
            else:
                parts.append(f"{title} ({format_when(when, now, self._lang)})")
        if len(items) > 3:
            parts.append("…")
        return ("、" if self._lang == "zh" else ", ").join(parts)

    def _compose_items(self, raw: str) -> list[tuple[str, datetime | None]]:
        raw = raw.strip()
        if not raw:
            return []
        items = extract_items(raw)
        if len(items) == 1 and items[0][1] is None and self._draft_remind is not None:
            return [(items[0][0], self._draft_remind)]
        return items

    def _insert_chip(self, prefix: str) -> None:
        current = self.input.text().strip()
        items = extract_items(current) if current else []
        if len(items) == 1 and items[0][1] is not None:
            current = items[0][0]
        self.input.setText(f"{prefix}{current}".strip() if prefix.endswith(" ") else f"{prefix}{current}")
        self.input.setFocus()
        self.input.end(False)

    def _apply_clock(self, when: datetime) -> None:
        self._picked_date = when.date()
        quarter = min(24 * 4 - 1, (when.hour * 60 + when.minute) // 15)
        self._time_slider.blockSignals(True)
        self._time_slider.setValue(quarter)
        self._time_slider.blockSignals(False)
        self._show_clock()

    def _show_clock(self) -> None:
        hour, minute = divmod(self._time_slider.value() * 15, 60)
        self._time_readout.setText(f"{hour:02d}:{minute:02d}")
        self._refresh_date_button()

    def _on_time_slider(self, _value: int) -> None:
        self._show_clock()

    def _selected_when(self) -> datetime:
        hour, minute = divmod(self._time_slider.value() * 15, 60)
        day = self._picked_date
        return datetime(day.year, day.month, day.day, hour, minute)

    def _apply_quick(self, minutes: int) -> None:
        self._apply_clock(datetime.now() + timedelta(minutes=minutes))

    def _refresh_date_button(self) -> None:
        day = self._picked_date
        if day == datetime.now().date():
            text = tr(self._lang, "today")
        elif self._lang == "zh":
            text = f"{day.month}月{day.day}日"
        else:
            text = f"{day:%b %d}"
        self._date_btn.setText(text)

    def _open_calendar(self) -> None:
        popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        popup.setObjectName("settings")
        layout = QVBoxLayout(popup)
        calendar = QCalendarWidget()
        calendar.setSelectedDate(QDate(self._picked_date.year, self._picked_date.month, self._picked_date.day))
        layout.addWidget(calendar)

        def choose(qdate: QDate) -> None:
            self._picked_date = datetime(qdate.year(), qdate.month(), qdate.day()).date()
            self._refresh_date_button()
            popup.hide()

        calendar.clicked.connect(choose)
        self._cal_popup = popup
        popup.installEventFilter(self)
        self._cal_held = True
        self._holds += 1
        anchor = self._date_btn.mapToGlobal(QPoint(0, self._date_btn.height() + 4))
        popup.move(anchor)
        popup.show()

    def _set_composer_priority(self, value: int) -> None:
        self._priority = value
        self._paint_priority()

    def _paint_priority(self) -> None:
        for value, button in self._priority_buttons.items():
            button.setText(_priority_label(self._lang, value))
            button.setStyleSheet(self._priority_style(value, value == self._priority))

    def _priority_style(self, value: int, selected: bool) -> str:
        theme = self.theme
        color = {
            PRIORITY_HIGH: theme.danger,
            PRIORITY_PLUS: theme.accent,
            PRIORITY_MID: theme.text,
            PRIORITY_LOW: theme.muted,
        }.get(value, theme.text)
        if selected:
            return (
                f"background: {theme.chip}; color: {color}; border: 1px solid {color}; "
                "border-radius: 8px; padding: 4px 2px; font-weight: 700;"
            )
        return (
            f"background: transparent; color: {color}; border: 1px solid {theme.line}; "
            "border-radius: 8px; padding: 4px 2px;"
        )

    def _row_priority_style(self, value: int) -> str:
        theme = self.theme
        color = {
            PRIORITY_HIGH: theme.danger,
            PRIORITY_PLUS: theme.accent,
            PRIORITY_MID: theme.muted,
            PRIORITY_LOW: theme.muted,
        }.get(value, theme.muted)
        return (
            f"QPushButton {{ background: transparent; color: {color}; border: none; "
            f"padding: 0 2px; font-size: 11px; }}"
        )

    def _edit_task(self, task_id: int) -> None:
        task = next((item for item in self.store.list_tasks() if item.id == task_id), None)
        if task is None:
            return
        theme = self.theme
        dialog = QDialog(self)
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        dialog.setModal(True)
        dialog.setStyleSheet(
            f"""
            QDialog {{ background: {theme.bg}; }}
            QLabel {{ color: {theme.text}; }}
            QLineEdit, QDateTimeEdit {{
                background: {theme.input}; color: {theme.text};
                border: 1px solid {theme.line}; border-radius: 8px; padding: 6px;
            }}
            QPushButton {{
                background: {theme.chip}; color: {theme.text}; border: none;
                border-radius: 8px; padding: 6px 10px;
            }}
            QPushButton#primary {{ background: {theme.accent}; color: {theme.accent_text}; font-weight: 700; }}
            """
        )
        layout = QVBoxLayout(dialog)
        title_edit = QLineEdit(task.title)
        layout.addWidget(title_edit)
        when_edit = QDateTimeEdit(task.remind_at or datetime.now())
        when_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        when_edit.setCalendarPopup(True)
        layout.addWidget(when_edit)
        chosen = {"priority": task.priority}
        rank = QHBoxLayout()
        buttons: dict[int, QPushButton] = {}

        def paint_rank() -> None:
            for value, button in buttons.items():
                button.setStyleSheet(self._priority_style(value, value == chosen["priority"]))

        for value in (PRIORITY_HIGH, PRIORITY_PLUS, PRIORITY_MID, PRIORITY_LOW):
            button = QPushButton(_priority_label(self._lang, value))
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, picked=value: _pick(picked))
            rank.addWidget(button)
            buttons[value] = button

        def _pick(value: int) -> None:
            chosen["priority"] = value
            paint_rank()

        paint_rank()
        layout.addLayout(rank)
        row = QHBoxLayout()
        cancel_btn = QPushButton(tr(self._lang, "cancel"))
        ok_btn = QPushButton(tr(self._lang, "ok"))
        ok_btn.setObjectName("primary")
        row.addStretch(1)
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        layout.addLayout(row)
        cancel_btn.clicked.connect(dialog.reject)

        def accept() -> None:
            title = title_edit.text().strip()
            if not title:
                return
            picked = when_edit.dateTime().toPython().replace(second=0, microsecond=0)
            self.store.update_task(task.id, title, picked, chosen["priority"])
            dialog.accept()

        ok_btn.clicked.connect(accept)
        dialog.adjustSize()
        center = self.frameGeometry().center()
        dialog.move(center.x() - dialog.width() // 2, center.y() - dialog.height() // 2)
        self._holds += 1
        try:
            if dialog.exec():
                self.reload()
        finally:
            self._holds = max(0, self._holds - 1)

    def _cycle_priority(self, task_id: int, current: int) -> None:
        self.store.set_priority(task_id, _next_priority(current))
        self.reload()

    def _add_from_composer(self) -> None:
        self._commit_text(self.input.text(), from_voice=False)

    def _commit_text(self, raw: str, from_voice: bool = False) -> None:
        items = self._compose_items(raw) if from_voice else []
        chosen = self._selected_when()
        if not from_voice:
            title = raw.strip()
            if not title:
                self._set_status(tr(self._lang, "need_text"))
                return
            items = [(title, chosen)]
        elif not items:
            self._set_status(tr(self._lang, "need_text"))
            return
        else:
            items = [(title, when or chosen) for title, when in items]
        for title, when in items:
            self.store.add_task(title, when, self._priority)
        self.input.clear()
        self._status = ""
        self._draft_remind = None
        self._focus_day(items)
        self.reload()

    def _focus_day(self, items: list[tuple[str, datetime | None]]) -> None:
        today = datetime.now().date()
        offsets = []
        for _title, when in items:
            if when is None:
                offsets.append(0)
                continue
            delta = (when.date() - today).days
            offsets.append(0 if delta <= 0 else delta if delta <= 2 else 3)
        if offsets:
            self._day = min(offsets)

    def _talk(self) -> None:
        if self.listener.running():
            self.listener.stop()
            self.talk_btn.setEnabled(False)
            return
        self._holds += 1
        self._listening = True
        self.talk_btn.set_listening(True)
        self._refresh_preview()
        self._stt_key = self.key_edit.text().strip()
        self.listener.start("en-US" if self._lang == "en" else "zh-CN", self._stt_key)

    def _on_speech(self, outcome) -> None:
        self._holds = max(0, self._holds - 1)
        self._listening = False
        self.talk_btn.setEnabled(True)
        self.talk_btn.set_listening(False)
        if outcome.ok and outcome.text:
            self.input.setText(outcome.text)
            self.activateWindow()
            self._commit_text(outcome.text, from_voice=True)
            return
        self._set_status(tr(self._lang, outcome.error or "err_failed"))
        self._refresh_preview()

    def _pick_draft_time(self) -> None:
        accepted, value = self._ask_time(self._draft_remind)
        if not accepted:
            return
        self._draft_remind = value
        self._refresh_preview()

    def _set_done(self, task_id: int, done: bool) -> None:
        self.store.set_done(task_id, done)
        self.reload()

    def _delete(self, task_id: int) -> None:
        self.store.delete(task_id)
        self.reload()

    def _snooze(self, task_id: int) -> None:
        self.store.update_remind(task_id, datetime.now() + timedelta(minutes=10))
        self._set_status(tr(self._lang, "snoozed"))
        self.reload()

    def _edit_time(self, task_id: int, current: datetime | None) -> None:
        accepted, value = self._ask_time(current)
        if not accepted:
            return
        self.store.update_remind(task_id, value)
        self.reload()

    def _ask_time(self, current: datetime | None) -> tuple[bool, datetime | None]:
        theme = self.theme
        dialog = QDialog()
        dialog.setWindowTitle(tr(self._lang, "time_title"))
        dialog.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        dialog.setModal(True)
        palette = dialog.palette()
        palette.setColor(QPalette.Window, QColor(theme.bg))
        palette.setColor(QPalette.WindowText, QColor(theme.text))
        palette.setColor(QPalette.Base, QColor(theme.input))
        palette.setColor(QPalette.Text, QColor(theme.text))
        palette.setColor(QPalette.Button, QColor(theme.chip))
        palette.setColor(QPalette.ButtonText, QColor(theme.text))
        dialog.setPalette(palette)
        dialog.setStyleSheet(
            f"""
            QDialog {{ background: {theme.bg}; }}
            QLabel {{ color: {theme.text}; }}
            QDateTimeEdit {{
                background: {theme.input}; color: {theme.text};
                border: 1px solid {theme.line}; border-radius: 8px; padding: 6px;
            }}
            QPushButton {{
                background: {theme.chip}; color: {theme.text}; border: none;
                border-radius: 8px; padding: 6px 10px;
            }}
            QPushButton#primary {{ background: {theme.accent}; color: {theme.accent_text}; font-weight: 700; }}
            """
        )
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(tr(self._lang, "time_label")))
        edit = QDateTimeEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        edit.setDateTime(current or (datetime.now() + timedelta(minutes=30)))
        layout.addWidget(edit)
        row = QHBoxLayout()
        clear_btn = QPushButton(tr(self._lang, "no_remind"))
        cancel_btn = QPushButton(tr(self._lang, "cancel"))
        ok_btn = QPushButton(tr(self._lang, "ok"))
        ok_btn.setObjectName("primary")
        row.addWidget(clear_btn)
        row.addStretch(1)
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        layout.addLayout(row)
        chosen: dict[str, datetime | None] = {"value": None}
        accepted = {"ok": False}

        def accept_value() -> None:
            accepted["ok"] = True
            picked = edit.dateTime().toPython()
            chosen["value"] = picked.replace(second=0, microsecond=0)
            dialog.accept()

        def accept_clear() -> None:
            accepted["ok"] = True
            chosen["value"] = None
            dialog.accept()

        ok_btn.clicked.connect(accept_value)
        clear_btn.clicked.connect(accept_clear)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.adjustSize()
        if self.x() > dialog.width() + 24:
            dialog.move(self.x() - dialog.width() - 12, self.y() + 80)
        else:
            dialog.move(self.x() + self.width() + 12, self.y() + 80)
        self._holds += 1
        try:
            dialog.exec()
        finally:
            self._holds = max(0, self._holds - 1)
        return accepted["ok"], chosen["value"]

    def _toggle_done_list(self) -> None:
        self._show_done = not self._show_done
        self._save()
        self.reload()

    def _toggle_pin(self, checked: bool) -> None:
        self._pinned = checked
        self.pin_btn.setText(tr(self._lang, "pinned" if checked else "pin"))
        if checked:
            self._suppress = False
        self._save()

    def _toggle_lang(self) -> None:
        self._lang = "en" if self._lang == "zh" else "zh"
        self._apply_texts()
        self._save()

    def _toggle_settings(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()
            return
        self._popup.adjustSize()
        anchor = self.settings_btn.mapToGlobal(QPoint(0, self.settings_btn.height() + 6))
        screen = QApplication.screenAt(anchor) or self._screen()
        if screen is not None:
            bounds = screen.availableGeometry()
            x = min(anchor.x(), bounds.right() - self._popup.width())
            y = min(anchor.y(), bounds.bottom() - self._popup.height())
            anchor = QPoint(max(bounds.left(), x), max(bounds.top(), y))
        if not self._popup_held:
            self._holds += 1
            self._popup_held = True
        self._popup.move(anchor)
        self._popup.show()
        self._paint_choices()

    def _set_theme(self, theme_id: str) -> None:
        self._theme_id = theme_id
        self._apply_theme()
        self.reload()
        self._save()

    def _set_day(self, day: int) -> None:
        self._day = day
        self.reload()

    def _save_key(self) -> None:
        self._stt_key = self.key_edit.text().strip()
        self._save()

    def _collapse(self) -> None:
        if self.pin_btn.isChecked():
            self.pin_btn.setChecked(False)
        if self._edge not in ("left", "right", "top"):
            self._edge = "right"
            current = self._screen()
            if current is not None:
                self._screen_key = screen_key(current)
        self._suppress = True
        self._grace_until = 0
        self._mode = CLOSED
        self.clearMask()
        self.update()
        self._animate_to(self._target_pos())
        self.clearFocus()
        self._save()

    def _open_from_user(self) -> None:
        self._suppress = False
        self._grace_until = _now() + 8
        self._mode = OPEN
        self.clearMask()
        self._animate_to(self._target_pos())
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def _set_status(self, text: str) -> None:
        self._status = text
        self._status_until = _now() + 6
        self._refresh_preview()

    def _check_reminders(self) -> None:
        now = datetime.now().replace(second=0, microsecond=0)
        due = self.store.due_tasks(now)
        if not due:
            return
        self.store.mark_reminded([task.id for task in due])
        if len(due) == 1:
            title = "GoodJob"
            body = due[0].title
        else:
            title = "GoodJob"
            body = "、".join(task.title for task in due[:4]) if self._lang == "zh" else ", ".join(task.title for task in due[:4])
        if self.tray.isSystemTrayAvailable():
            self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 8000)
        self._day = 0
        self._suppress = False
        self._grace_until = _now() + 12
        self._mode = OPEN
        self._animate_to(self._target_pos())
        self.reload()

    def _tick(self) -> None:
        if self._dragging and not (QApplication.mouseButtons() & Qt.LeftButton):
            self._end_drag()
        if self._dragging:
            return
        self._sync_size()
        docked = self._edge in ("left", "right", "top")
        inside = self._hot_rect().contains(QCursor.pos())
        if self._suppress and not inside:
            self._suppress = False
        if inside:
            self._outside_at = None
        elif self._mode == OPEN and self._outside_at is None:
            self._outside_at = _now()
        outside_for = None if self._outside_at is None else _now() - self._outside_at
        desired_open = want_open(
            pinned=self._pinned,
            held=self._holds > 0,
            grace=_now() < self._grace_until,
            suppressed=self._suppress,
            inside=inside,
            opened=self._mode == OPEN,
            outside_for=outside_for,
            docked=docked,
            delay=HIDE_DELAY,
        )
        desired = OPEN if desired_open else CLOSED
        animating = hasattr(self, "_anim") and self._anim.state() == QAbstractAnimation.Running
        if desired != self._mode:
            self._mode = desired
            if desired == CLOSED:
                self.clearFocus()
            self._animate_to(self._target_pos())
            return
        if not animating and self.pos() != self._target_pos():
            self.move(self._target_pos())

    def _sync_size(self) -> None:
        avail = self._avail()
        height = min(PANEL_HEIGHT, max(480, avail.height() - 40))
        if self.width() != PANEL_WIDTH or self.height() != height:
            self.setFixedSize(PANEL_WIDTH, height)
            self.clearMask()

    def _screen(self):
        screens = QApplication.screens()
        if self._screen_key:
            for screen in screens:
                if screen_key(screen) == self._screen_key:
                    return screen
        found = QApplication.screenAt(self.frameGeometry().center())
        if found is not None:
            return found
        return QApplication.primaryScreen() or (screens[0] if screens else None)

    def _avail(self) -> QRect:
        screen = self._screen()
        if screen is None:
            return QRect(0, 0, 1920, 1080)
        return screen.availableGeometry()

    def _target_pos(self) -> QPoint:
        avail = self._avail()
        box = Box(avail.left(), avail.top(), avail.right(), avail.bottom())
        ax = self._ax if isinstance(self._ax, int) else avail.left() + 48
        ay = self._ay if isinstance(self._ay, int) else avail.top() + max(0, (avail.height() - self.height()) // 2)
        x, y = placed(self._edge, ax, ay, self.width() or PANEL_WIDTH, self.height() or PANEL_HEIGHT, box, self._mode == OPEN, PEEK)
        return QPoint(x, y)

    def _animate_to(self, target: QPoint) -> None:
        if not hasattr(self, "_anim"):
            self.move(target)
            return
        if self.pos() == target:
            return
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(target)
        self._anim.start()

    def _hot_rect(self) -> QRect:
        screen = self._screen()
        visible = self.frameGeometry()
        if screen is not None:
            visible = visible.intersected(screen.geometry())
        if self._mode == OPEN or self._edge not in ("left", "right", "top"):
            return visible.adjusted(-10, -10, 10, 10)
        if self._edge == "right":
            return visible.adjusted(-22, -24, 4, 24)
        if self._edge == "left":
            return visible.adjusted(-4, -24, 22, 24)
        return visible.adjusted(-24, -4, 24, 22)

    def _apply_mask(self) -> None:
        self.clearMask()

    def _tray_activated(self, reason) -> None:
        trigger = QSystemTrayIcon.ActivationReason.Trigger
        double = QSystemTrayIcon.ActivationReason.DoubleClick
        if reason in (trigger, double):
            self._open_from_user()

    def _quit(self) -> None:
        self.shutdown()
        QApplication.quit()

    def _save(self) -> None:
        save_config(
            {
                "language": self._lang,
                "theme": self._theme_id,
                "edge": self._edge or "none",
                "x": self._ax,
                "y": self._ay,
                "screen": self._screen_key,
                "pinned": self._pinned,
                "done_open": self._show_done,
                "groq_key": self._stt_key,
            }
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = panel_path(self.width(), self.height(), self._edge)
        painter.fillPath(path, QColor(self.theme.bg))
        painter.setClipPath(path)
        bar = QColor(self.theme.bar)
        if self._edge == "left":
            painter.fillRect(self.width() - 6, 0, 6, self.height(), bar)
        elif self._edge == "top":
            painter.fillRect(0, self.height() - 6, self.width(), 6, bar)
        else:
            painter.fillRect(0, 0, 6, self.height(), bar)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(self.theme.border), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()

    def showEvent(self, event) -> None:
        if not hasattr(self, "_anim"):
            self._anim = QPropertyAnimation(self, b"pos", self)
            self._anim.setDuration(180)
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.clearMask()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self.clearMask()
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:
        if self._shut:
            event.accept()
            return
        event.ignore()
        self._collapse()

    def mousePressEvent(self, event) -> None:
        self.activateWindow()
        if event.button() == Qt.LeftButton and event.position().y() < 36:
            self._begin_drag(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._drag_to(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._end_drag()
        super().mouseReleaseEvent(event)

    def _end_drag(self) -> None:
        if not self._dragging:
            return
        self._dragging = False
        if self.mouseGrabber() is self:
            self.releaseMouse()
        self.clearMask()
        self.update()
        self._save()

    def _begin_drag(self, global_point: QPoint) -> None:
        self._dragging = True
        self._grab = global_point - self.pos()
        if hasattr(self, "_anim"):
            self._anim.stop()
        self.grabMouse()

    def _drag_to(self, cursor: QPoint) -> None:
        screen = QApplication.screenAt(cursor) or self._screen()
        if screen is None:
            return
        self._screen_key = screen_key(screen)
        avail = screen.availableGeometry()
        box = Box(avail.left(), avail.top(), avail.right(), avail.bottom())
        proposed = cursor - self._grab
        edge = snap_edge(proposed.x(), proposed.y(), self.width(), self.height(), box)
        self._edge = edge
        self._mode = OPEN
        x, y = placed(edge, proposed.x(), proposed.y(), self.width(), self.height(), box, True, PEEK)
        self._ax, self._ay = x, y
        self.move(x, y)
        self.update()

    def event(self, event) -> bool:
        if event.type() in (QEvent.UngrabMouse, QEvent.WindowDeactivate) and self._dragging:
            self._end_drag()
        return super().event(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "_cal_popup", None) and event.type() == QEvent.Hide and getattr(self, "_cal_held", False):
            self._cal_held = False
            self._holds = max(0, self._holds - 1)
            return False
        if watched is self._popup and event.type() == QEvent.Hide:
            if self._popup_held:
                self._popup_held = False
                self._holds = max(0, self._holds - 1)
            return False
        if watched is self._stage and event.type() == QEvent.Resize:
            self._layout_stage()
            return False
        if watched in (self._header, self.name_label) and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.activateWindow()
            self._begin_drag(event.globalPosition().toPoint())
            return True
        if event.type() == QEvent.MouseButtonRelease and self._dragging:
            self._end_drag()
            return True
        return super().eventFilter(watched, event)


def QRegion_from(polygon):
    from PySide6.QtGui import QRegion

    return QRegion(polygon)


def _bucket(task: Task, today) -> int:
    day = task.remind_at.date() if task.remind_at is not None else task.created_at.date()
    delta = (day - today).days
    if delta == 0:
        return 0
    if delta == 1:
        return 1
    if delta == 2:
        return 2
    if delta > 2:
        return 3
    return -1


def _is_due(task: Task, now: datetime) -> bool:
    return (not task.done) and task.remind_at is not None and task.remind_at <= now


def _open_sort(task: Task, now: datetime) -> tuple:
    return (task.priority, task.remind_at or task.created_at)


def _priority_label(lang: str, value: int) -> str:
    return tr(lang, {0: "pri_high", 1: "pri_plus", 2: "pri_mid", 3: "pri_low"}.get(value, "pri_mid"))


def _wrap_lines(text: str, font: QFont, width: int, max_lines: int) -> str:
    metrics = QFontMetrics(font)
    layout = QTextLayout(text, font)
    layout.beginLayout()
    pieces: list[str] = []
    used = 0
    for _ in range(max_lines):
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        pieces.append(text[line.textStart() : line.textStart() + line.textLength()])
        used = line.textStart() + line.textLength()
    layout.endLayout()
    if used < len(text) and pieces:
        pieces[-1] = metrics.elidedText(pieces[-1] + text[used:], Qt.ElideRight, width)
    return "\n".join(pieces) if pieces else text


def _next_priority(value: int) -> int:
    order = (PRIORITY_HIGH, PRIORITY_PLUS, PRIORITY_MID, PRIORITY_LOW)
    try:
        return order[(order.index(value) + 1) % len(order)]
    except ValueError:
        return PRIORITY_MID


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def _clamp_opacity(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.96
    return min(1.0, max(0.6, number))


def _now() -> float:
    import time

    return time.monotonic()
