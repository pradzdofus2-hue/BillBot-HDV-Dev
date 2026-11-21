from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton, TitleLabel

from src.consts import LOGO_FILE
from src.services.github_auth import DEVICE_PAGE


class StartupPage(QWidget):
    retry_requested = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("startup")
        card = CardWidget(self)
        card.setMaximumWidth(460)
        card.setMinimumWidth(340)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(32, 30, 32, 30)
        layout.setSpacing(16)
        logo = BodyLabel(card)
        logo.setPixmap(
            QPixmap(LOGO_FILE).scaled(
                48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )
        layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.title = TitleLabel(card)
        layout.addWidget(self.title, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.status = BodyLabel(card)
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        self.code = TitleLabel(card)
        self.code.setTextFormat(Qt.TextFormat.PlainText)
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.code, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.device_actions = QWidget(card)
        buttons = QHBoxLayout(self.device_actions)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.copy_button = PushButton("Copy code", self.device_actions)
        self.copy_button.clicked.connect(self._copy_code)
        open_button = PrimaryPushButton("Open GitHub", self.device_actions)
        open_button.clicked.connect(self._open_browser)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(open_button)
        layout.addWidget(self.device_actions)
        self.retry = PrimaryPushButton("Try again", card)
        self.retry.clicked.connect(self.retry_requested.emit)
        layout.addWidget(self.retry, alignment=Qt.AlignmentFlag.AlignHCenter)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        self.show_status("Preparing startup…")

    def show_status(self, message: str, *, error: bool = False) -> None:
        self.title.setText("Startup interrupted" if error else "Starting AstraBot")
        self.device_actions.hide()
        self.code.hide()
        self.code.clear()
        self.status.setText(message)
        self.retry.setVisible(error)

    def show_device_code(self, code: str) -> None:
        self.title.setText("Connect to GitHub")
        self.status.setText("Enter this one-time code on GitHub to authorize AstraBot.")
        self.code.setText(code)
        self.copy_button.setText("Copy code")
        self.retry.hide()
        self.code.show()
        self.device_actions.show()
        self._open_browser()

    def _copy_code(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.code.text())
            self.copy_button.setText("Copied")

    def _open_browser(self) -> None:
        if not QDesktopServices.openUrl(QUrl(DEVICE_PAGE)):
            self.status.setText(f"Open {DEVICE_PAGE} in your browser and enter this code.")
