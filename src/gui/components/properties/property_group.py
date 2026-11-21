from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import HeaderCardWidget

from src.gui.components.properties.property_row import PropertyRow


class PropertyGroup(HeaderCardWidget):
    def __init__(self, key: str, vertical: bool = False, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.setTitle(key)
        self.headerLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.headerLayout.setContentsMargins(16, 0, 16, 0)
        self.viewLayout.setContentsMargins(16, 12, 16, 16)
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.viewLayout.addLayout(self.content_layout)
        self._vertical = vertical
        self._active = True
        self.property_by_key: dict[str, PropertyRow] = {}
        self.hide()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.setVisible(active and bool(self.property_by_key))

    def add_or_update_property_label(self, key: str, value: str) -> None:
        property_widget: PropertyRow | None = self.property_by_key.get(key)
        if property_widget is not None:
            property_widget.set_content_value(value)
        else:
            property_widget = PropertyRow(key=key, value=value, vertical=self._vertical)
            self.content_layout.addWidget(property_widget)
            self.property_by_key[key] = property_widget
        self.setVisible(self._active and bool(self.property_by_key))
