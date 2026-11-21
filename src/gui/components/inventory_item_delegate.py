from PyQt6.QtCore import QModelIndex, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QListView, QStyle, QStyleOptionViewItem
from qfluentwidgets import ListItemDelegate


class InventoryItemDelegate(ListItemDelegate):
    def __init__(self, parent: QListView, icons: dict[int, QIcon | None]) -> None:
        super().__init__(parent)
        self._icons = icons

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if painter is None or index.data(Qt.ItemDataRole.UserRole + 2):
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(option.rect).adjusted(3, 3, -3, -3)
        selected = index.row() in self.selectedRows or bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == self.hoverRow or bool(option.state & QStyle.StateFlag.State_MouseOver)
        background = QLinearGradient(card.topLeft(), card.bottomRight())
        background.setColorAt(0, QColor("#303142" if hovered else "#282937"))
        background.setColorAt(1, QColor("#1d1e2b"))
        painter.setBrush(background)
        painter.setPen(QPen(QColor("#8199bf" if selected else "#444657"), 1))
        painter.drawRoundedRect(card, 3, 3)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#14151e"), 1))
        painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 2, 2)

        icon_id = index.data(Qt.ItemDataRole.UserRole + 1)
        icon = self._icons.get(icon_id) if isinstance(icon_id, int) else None
        if icon is not None and not icon.isNull():
            icon.paint(painter, card.adjusted(5, 5, -5, -5).toRect(), Qt.AlignmentFlag.AlignCenter)
        else:
            font = option.font
            font.setPixelSize(11)
            painter.setFont(font)
            painter.setPen(QColor("#c6c6d1"))
            painter.drawText(
                card.adjusted(5, 20, -5, -5),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            )

        quantity = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(quantity, int) and quantity > 1:
            font = option.font
            font.setPixelSize(13)
            painter.setFont(font)
            text = QPainterPath()
            text.addText(QPointF(card.left() + 4, card.top() + 16), font, str(quantity))
            painter.setPen(
                QPen(
                    QColor("#101018"),
                    2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.strokePath(text, painter.pen())
            painter.fillPath(text, QColor("#ffffff"))
        painter.restore()
