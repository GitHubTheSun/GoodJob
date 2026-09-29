"""PySide6 on newer Windows, PySide2 when building for Windows 7."""

try:
    from PySide6.QtCore import (
        QAbstractAnimation,
        QObject,
        QDate,
        QEasingCurve,
        QEvent,
        QParallelAnimationGroup,
        QPoint,
        QPropertyAnimation,
        QRect,
        QSize,
        Qt,
        QTimer,
        Signal,
    )
    from PySide6.QtGui import (
        QColor,
        QCursor,
        QFont,
        QFontDatabase,
        QFontMetrics,
        QIcon,
        QPainter,
        QPainterPath,
        QPalette,
        QPen,
        QPixmap,
        QRegion,
        QTextLayout,
    )
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
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
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSlider,
        QSystemTrayIcon,
        QVBoxLayout,
        QWidget,
    )

    PYSIDE = 6
except ImportError:
    from PySide2.QtCore import (
        QAbstractAnimation,
        QObject,
        QDate,
        QEasingCurve,
        QEvent,
        QParallelAnimationGroup,
        QPoint,
        QPropertyAnimation,
        QRect,
        QSize,
        Qt,
        QTimer,
        Signal,
    )
    from PySide2.QtGui import (
        QColor,
        QCursor,
        QFont,
        QFontDatabase,
        QFontMetrics,
        QIcon,
        QPainter,
        QPainterPath,
        QPalette,
        QPen,
        QPixmap,
        QRegion,
        QTextLayout,
    )
    from PySide2.QtNetwork import QLocalServer, QLocalSocket
    from PySide2.QtWidgets import (
        QApplication,
        QCalendarWidget,
        QDateTimeEdit,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSlider,
        QSystemTrayIcon,
        QVBoxLayout,
        QWidget,
    )

    PYSIDE = 2


def run_exec(widget):
    method = getattr(widget, "exec", None)
    if not callable(method):
        method = widget.exec_
    return method()


def to_datetime(value):
    if hasattr(value, "toPython"):
        return value.toPython()
    if hasattr(value, "toPyDateTime"):
        return value.toPyDateTime()
    return value.toPyDate()


def global_point(event):
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


def local_y(event) -> float:
    if hasattr(event, "position"):
        return event.position().y()
    return event.pos().y()


def tray_clicks():
    enum = getattr(QSystemTrayIcon, "ActivationReason", None)
    if enum is not None and hasattr(enum, "Trigger"):
        return enum.Trigger, enum.DoubleClick
    return QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick
