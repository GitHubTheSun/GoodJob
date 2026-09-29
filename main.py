"""GoodJob：可拖动的记事和提醒。拖到屏幕边缘会吸附。"""

from __future__ import annotations

import sys
import traceback

from goodjob.qt_compat import (
    QApplication,
    QColor,
    QFont,
    QFontDatabase,
    QLocalServer,
    QLocalSocket,
    QMessageBox,
    QPalette,
    Qt,
    run_exec,
)

from goodjob.store import data_dir
from goodjob.window import DockWindow, make_icon

SERVER_NAME = "GoodJob.Dock"


def main() -> int:
    _install_excepthook()
    rounding = getattr(getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None), "PassThrough", None)
    if rounding is not None and hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(rounding)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("GoodJob")
    app.setFont(_ui_font())
    app.setWindowIcon(make_icon())
    _apply_dark(app)

    if not _claim_single_instance(app):
        return 0

    window = DockWindow()
    app.aboutToQuit.connect(window.shutdown)
    window.start()
    return run_exec(app)


def _ui_font() -> QFont:
    try:
        families = QFontDatabase.families()
    except TypeError:
        families = QFontDatabase().families()
    if "Microsoft YaHei UI" in families:
        return QFont("Microsoft YaHei UI", 10)
    if "Microsoft YaHei" in families:
        return QFont("Microsoft YaHei", 10)
    return QFont("SimSun", 10)


def _claim_single_instance(app: QApplication) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if socket.waitForConnected(200):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(200)
        socket.disconnectFromServer()
        return False

    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer(app)
    if not server.listen(SERVER_NAME):
        return True

    def accept() -> None:
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            if client is not None:
                client.waitForReadyRead(100)
                client.disconnectFromServer()
        for widget in app.topLevelWidgets():
            if isinstance(widget, DockWindow):
                widget._open_from_user()

    server.newConnection.connect(accept)
    app._goodjob_server = server  # 防止被回收
    return True


def _apply_dark(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#22262f"))
    palette.setColor(QPalette.WindowText, QColor("#f4f1ea"))
    palette.setColor(QPalette.Base, QColor("#2a2f3a"))
    palette.setColor(QPalette.AlternateBase, QColor("#22262f"))
    palette.setColor(QPalette.Text, QColor("#f4f1ea"))
    palette.setColor(QPalette.Button, QColor("#2a2f3a"))
    palette.setColor(QPalette.ButtonText, QColor("#f4f1ea"))
    palette.setColor(QPalette.Highlight, QColor("#e2a33a"))
    palette.setColor(QPalette.HighlightedText, QColor("#1a1408"))
    palette.setColor(QPalette.ToolTipBase, QColor("#22262f"))
    palette.setColor(QPalette.ToolTipText, QColor("#f4f1ea"))
    palette.setColor(QPalette.PlaceholderText, QColor("#8b919c"))
    app.setPalette(palette)


def _install_excepthook() -> None:
    def hook(exc_type, value, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, value, tb))
        try:
            (data_dir() / "error.log").write_text(text, encoding="utf-8")
        except OSError:
            pass
        sys.__excepthook__(exc_type, value, tb)

    sys.excepthook = hook


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        text = traceback.format_exc()
        try:
            (data_dir() / "error.log").write_text(text, encoding="utf-8")
        except OSError:
            pass
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "GoodJob", "启动失败，详情写在本地 GoodJob\\error.log")
        raise
