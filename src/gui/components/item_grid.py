from __future__ import annotations

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectItemInventory
from PyQt6.QtCore import QPoint, QSize, QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QIcon, QImage, QPixmap, QResizeEvent, QShowEvent
from PyQt6.QtWidgets import QGridLayout, QListView, QListWidgetItem, QWidget
from qfluentwidgets import CaptionLabel, ListWidget, SmoothMode

from src.gui.components.inventory_item_delegate import InventoryItemDelegate
from src.gui.services.item_icons import ICON_SIZE, item_icon_cache
from src.gui.utils.item_display import get_item_display

CELL_SIZE = 80
CELL_SPACING = 6
GRID_SCROLLBAR_SPACE = 20


class ItemGridContainer(QWidget):
    def __init__(self, grid: ItemGrid, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grid = grid
        self.setMinimumWidth(CELL_SIZE + GRID_SCROLLBAR_SPACE)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(grid, 0, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.placeholder = CaptionLabel(parent=self)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.hide()
        layout.addWidget(self.placeholder, 0, 0)

    def set_placeholder(self, text: str) -> None:
        self.placeholder.setText(text)
        self.placeholder.setVisible(bool(text))
        self.grid.setVisible(not text)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        columns = max(1, (self.width() - GRID_SCROLLBAR_SPACE) // CELL_SIZE)
        self.grid.setFixedWidth(columns * CELL_SIZE + GRID_SCROLLBAR_SPACE)


class ItemGrid(ListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._display_icons: dict[int, QIcon | None] = {}
        self._icons = item_icon_cache()
        self._icons.ready.connect(self._on_icon_ready)
        self._icon_timer = QTimer(self)
        self._icon_timer.setSingleShot(True)
        self._icon_timer.setInterval(30)
        self._icon_timer.timeout.connect(self._load_visible_icons)
        self.setItemDelegate(InventoryItemDelegate(self, self._display_icons))
        self.scrollDelegate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSpacing(CELL_SPACING)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(CELL_SIZE, CELL_SIZE))
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        viewport = self.viewport()
        scrollbar = self.verticalScrollBar()
        assert viewport is not None and scrollbar is not None
        self._viewport = viewport
        scrollbar.valueChanged.connect(self._schedule_icons)
        self.setStyleSheet("QListWidget { background-color: transparent; border: none; }")

    def add_object_item(self, object_item: ObjectItemInventory) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setSizeHint(QSize(CELL_SIZE, CELL_SIZE))
        name, icon_id = get_item_display(object_item.item.gid)
        item.setText(name)
        item.setToolTip(name)
        item.setData(Qt.ItemDataRole.UserRole, object_item.item.quantity)
        if icon_id is not None:
            item.setData(Qt.ItemDataRole.UserRole + 1, icon_id)
            if icon_id not in self._display_icons:
                image = self._icons.cached(icon_id)
                self._display_icons[icon_id] = QIcon(QPixmap.fromImage(image)) if image is not None else None
        self.addItem(item)
        self._schedule_icons()
        return item

    def clear(self) -> None:
        self._icon_timer.stop()
        self._display_icons.clear()
        super().clear()

    def _schedule_icons(self) -> None:
        if self.isVisible() and not self._icon_timer.isActive():
            self._icon_timer.start()

    def _load_visible_icons(self) -> None:
        if not self.isVisible():
            return
        viewport = self._viewport.rect()
        if viewport.isEmpty():
            return
        rows: set[int] = set()
        xs = {*range(0, viewport.width(), CELL_SIZE // 2), viewport.right()}
        ys = {*range(0, viewport.height(), CELL_SIZE // 2), viewport.bottom()}
        for y in ys:
            for x in xs:
                index = self.indexAt(QPoint(x, y))
                if index.isValid():
                    rows.add(index.row())
        requested: set[int] = set()
        for row in sorted(rows, reverse=True):
            item = self.item(row)
            if item is None:
                continue
            icon_id = item.data(Qt.ItemDataRole.UserRole + 1)
            if (
                not isinstance(icon_id, int)
                or icon_id in requested
                or self._display_icons.get(icon_id) is not None
            ):
                continue
            requested.add(icon_id)
            image = self._icons.request(icon_id)
            if image is not None:
                self._on_icon_ready(icon_id, image)

    @pyqtSlot(int, QImage)
    def _on_icon_ready(self, icon_id: int, image: QImage) -> None:
        if icon_id in self._display_icons and self.isVisible():
            self._display_icons[icon_id] = QIcon(QPixmap.fromImage(image))
            self._viewport.update()

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self._schedule_icons()

    def resizeEvent(self, e: QResizeEvent | None) -> None:
        super().resizeEvent(e)
        self._schedule_icons()
