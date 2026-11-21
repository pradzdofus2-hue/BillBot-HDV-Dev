from collections.abc import Callable
import logging

from pydantic import ValidationError
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QHideEvent, QShowEvent
from PyQt6.QtWidgets import QFormLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, LineEdit
from qfluentwidgets.components.dialog_box.dialog import MessageBox

from src.gui.pages.settings.settings_overview import SettingsOverview
from src.services.background import run_in_background
from src.utils.runtime_support import RuntimeSetupError, error_message

logger = logging.getLogger(__name__)
SAVE_DELAY_MS = 2_000


class SettingsPanel(QWidget):
    saved = pyqtSignal()

    def __init__(self, description: str) -> None:
        super().__init__()
        self._saving = False
        self._dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.flush_save)
        self._deletion_handlers: dict[SettingsOverview, Callable[[str], None]] = {}
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        label = BodyLabel(description, self)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addSpacing(16)
        self.overview_layout = QVBoxLayout()
        layout.addLayout(self.overview_layout)
        self.form = QFormLayout()
        self.form.setVerticalSpacing(12)
        self.form.setHorizontalSpacing(20)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addLayout(self.form)
        layout.addStretch()

    def queue_save(self) -> None:
        if self.isEnabled() and not self._saving:
            self._dirty = True
            self._save_timer.start()

    def flush_save(self) -> None:
        if not self._dirty or self._saving:
            return
        self._save_timer.stop()
        self._saving = True
        try:
            self.save()
        except ValidationError:
            self.invalid("Invalid configuration. Check the provided fields.")
        except ValueError as error:
            self.invalid(str(error))

    def finish_edit(self) -> None:
        self.flush_save()
        self._dirty = False

    def line(self, label: str) -> LineEdit:
        widget = LineEdit(self)
        self.form.addRow(BodyLabel(label, self), widget)
        widget.textEdited.connect(self.queue_save)
        return widget

    def combo(self, label: str, items: list[str] | None = None) -> ComboBox:
        widget = ComboBox(self)
        if items:
            widget.addItems(items)
        self.form.addRow(BodyLabel(label, self), widget)
        widget.activated.connect(self.queue_save)
        return widget

    def overview(self, headers: list[str], new_label: str | None = None) -> SettingsOverview:
        widget = SettingsOverview(headers, self, new_label)
        self.overview_layout.addWidget(widget)
        return widget

    def bind_deletion(
        self,
        overview: SettingsOverview,
        action: Callable[[str], None],
        on_deleted: Callable[[], None] | None = None,
        *,
        background: bool = True,
    ) -> None:
        def request(identifier: str) -> None:
            confirmation = MessageBox(
                "Delete permanently",
                f"Permanently delete {identifier}? This action cannot be undone.",
                self.window(),
            )
            confirmation.yesButton.setText("Delete")
            confirmation.cancelButton.setText("Cancel")
            if not confirmation.exec():
                return

            def done(_: None) -> None:
                if on_deleted is not None:
                    on_deleted()
                self.reload()

            self.perform(lambda: action(identifier), done, background=background)

        previous = self._deletion_handlers.get(overview)
        if previous is not None:
            overview.delete_requested.disconnect(previous)
        self._deletion_handlers[overview] = request
        overview.delete_requested.connect(request)

    def perform[ResultT](
        self,
        action: Callable[[], ResultT],
        done: Callable[[ResultT], None],
        *,
        background: bool = True,
    ) -> None:
        self.setEnabled(False)

        def work(_: Callable[[str], None]) -> ResultT:
            try:
                return action()
            except ValidationError as error:
                raise RuntimeSetupError("Invalid configuration. Check the provided fields.") from error
            except ValueError as error:
                raise RuntimeSetupError(str(error)) from error

        def success(result: ResultT) -> None:
            saved = self._saving
            self._saving = False
            if saved:
                self._dirty = False
            self.setEnabled(True)
            done(result)
            if saved:
                self.saved.emit()

        def failure(error: object) -> None:
            self._saving = False
            self.setEnabled(True)
            logger.warning("Settings operation failed: %s", error_message(error))

        if background:
            run_in_background(work, on_success=success, on_error=failure, parent=self)
        else:
            try:
                result = work(lambda _: None)
            except RuntimeSetupError as error:
                failure(error)
            else:
                success(result)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        if self.isEnabled() and not self._dirty:
            self.reload()

    def hideEvent(self, a0: QHideEvent | None) -> None:
        self.flush_save()
        super().hideEvent(a0)

    def reload(self) -> None:
        raise NotImplementedError

    def save(self) -> None:
        raise NotImplementedError

    def invalid(self, message: str = "Check the numeric field values.") -> None:
        self._saving = False
        logger.warning("Settings were not saved: %s", message)
