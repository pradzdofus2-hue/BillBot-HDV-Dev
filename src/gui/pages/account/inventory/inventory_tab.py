from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel

from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import (
    ObjectItemInventory,
)
from DBDofusUnity.dofus_unity_reader.game_constants.inventory_position import (
    CharacterInventoryPositionEnum,
)
from src.gui.components.item_grid import GRID_SCROLLBAR_SPACE, ItemGrid, ItemGridContainer
from src.gui.pages.account.inventory.bank_panel import BankPanel
from src.gui.pages.account.inventory.equipment_panel import (
    EquipmentPanel,
)
lazy from src.core.bot.bot import Bot

_NOT_EQUIPED = int(CharacterInventoryPositionEnum.InventoryPositionNotEquiped)


class InventoryTab(QWidget):
    def __init__(self, bot: Bot, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.bot = bot
        self.items_by_uid: dict[int, ObjectItemInventory] = {}
        self.signals_connected = False
        self.inventory_weight: int = 0
        self.weight_max: int = 0
        self._render_dirty = False
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setInterval(50)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.timeout.connect(self._rebuild_sorted_list)

        self.equipment_panel = EquipmentPanel(self)
        self.equipment_panel.hide()

        self.list_widget = ItemGrid(self)
        self.grid_container = ItemGridContainer(self.list_widget, self)
        self.grid_container.set_placeholder("Inventory data has not been received yet.")
        self.weight_label = BodyLabel(text="Weight: 0/0", parent=self)
        self.weight_label.hide()
        self.loading_label = CaptionLabel(text="Loading inventory…", parent=self)
        self.loading_label.hide()
        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self.weight_label)
        bottom_layout.addWidget(self.loading_label)
        bottom_layout.addStretch(1)

        content_layout = QHBoxLayout()
        content_layout.addWidget(self.equipment_panel)
        inventory_layout = QVBoxLayout()
        self.inventory_title = BodyLabel(text="Inventory", parent=self)
        self.inventory_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inventory_layout.addWidget(self.inventory_title)
        inventory_layout.addWidget(self.grid_container, 1)
        inventory_layout.addLayout(bottom_layout)
        content_layout.addLayout(inventory_layout, 1)
        self.bank_panel = BankPanel(bot, self)
        content_layout.addWidget(self.bank_panel, 1)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addLayout(content_layout, 1)

    @pyqtSlot(ObjectItemInventory)
    def on_added_object_item(self, object_item: ObjectItemInventory):
        self.items_by_uid[object_item.item.uid] = object_item
        self._schedule_rebuild()

    @pyqtSlot(list)
    def on_added_object_items_batch(self, objects: list[ObjectItemInventory]):
        for object_item in objects:
            self.items_by_uid[object_item.item.uid] = object_item
        self._schedule_rebuild()

    @pyqtSlot(int)
    def on_deleted_object_item_uid(self, uid: int):
        if uid not in self.items_by_uid:
            return
        del self.items_by_uid[uid]
        self._schedule_rebuild()

    @pyqtSlot(ObjectItemInventory)
    def on_updated_object_item(self, object_item: ObjectItemInventory):
        if object_item.item.uid not in self.items_by_uid:
            return
        self.items_by_uid[object_item.item.uid] = object_item
        self._schedule_rebuild()

    @pyqtSlot()
    def on_clear_inventory(self):
        self.items_by_uid.clear()
        self._rebuild_timer.stop()
        if self.isVisible():
            self._rebuild_sorted_list()
        else:
            self._render_dirty = True

    @pyqtSlot(int)
    def on_inventory_weight_updated(self, inventory_weight: int):
        self.inventory_weight = inventory_weight
        self._refresh_weight_label()

    @pyqtSlot(int)
    def on_weight_max_updated(self, weight_max: int):
        self.weight_max = weight_max
        self._refresh_weight_label()

    def _refresh_weight_label(self) -> None:
        self.weight_label.setText(f"Weight: {self.inventory_weight}/{self.weight_max}")

    def _schedule_rebuild(self) -> None:
        self._render_dirty = True
        if self.isVisible() and not self._rebuild_timer.isActive():
            self.loading_label.show()
            self._rebuild_timer.start()

    def _rebuild_sorted_list(self) -> None:
        equipped_by_position: dict[int, ObjectItemInventory] = {}
        bag_items: list[ObjectItemInventory] = []
        for object_item in self.items_by_uid.values():
            if object_item.position == _NOT_EQUIPED:
                bag_items.append(object_item)
            else:
                equipped_by_position[object_item.position] = object_item

        self.equipment_panel.set_items(equipped_by_position)

        content_known = self.bot.game_state.inventory.inventory_content_known or bool(self.items_by_uid)
        self.equipment_panel.setVisible(content_known)
        self.weight_label.setVisible(content_known)
        if not content_known:
            placeholder = "Inventory data has not been received yet."
        elif not bag_items:
            placeholder = "Your bag is empty."
        else:
            placeholder = ""
        self.grid_container.set_placeholder(placeholder)
        self.inventory_title.setContentsMargins(0, 0, GRID_SCROLLBAR_SPACE if bag_items else 0, 0)

        self.list_widget.setUpdatesEnabled(False)
        self.list_widget.clear()
        sorted_items = sorted(bag_items, key=lambda obj: obj.item.quantity, reverse=True)
        for object_item in sorted_items:
            self.list_widget.add_object_item(object_item)
        self.list_widget.setUpdatesEnabled(True)
        self._render_dirty = False
        self.loading_label.hide()

    def connect_signals(self) -> None:
        if self.signals_connected:
            return
        self.bot.inventory_signals.added_object_item.connect(self.on_added_object_item)
        self.bot.inventory_signals.added_object_items_batch.connect(self.on_added_object_items_batch)
        self.bot.inventory_signals.updated_object_item.connect(self.on_updated_object_item)
        self.bot.inventory_signals.deleted_object_item_uid.connect(self.on_deleted_object_item_uid)
        self.bot.inventory_signals.clear_inventory.connect(self.on_clear_inventory)
        self.bot.inventory_signals.inventory_weight.connect(self.on_inventory_weight_updated)
        self.bot.inventory_signals.weight_max.connect(self.on_weight_max_updated)
        self.bank_panel.connect_signals()
        self.signals_connected = True
        self._resync_inventory()

    def disconnect_signals(self) -> None:
        if not self.signals_connected:
            return
        self.bot.inventory_signals.added_object_item.disconnect(self.on_added_object_item)
        self.bot.inventory_signals.added_object_items_batch.disconnect(self.on_added_object_items_batch)
        self.bot.inventory_signals.updated_object_item.disconnect(self.on_updated_object_item)
        self.bot.inventory_signals.deleted_object_item_uid.disconnect(self.on_deleted_object_item_uid)
        self.bot.inventory_signals.clear_inventory.disconnect(self.on_clear_inventory)
        self.bot.inventory_signals.inventory_weight.disconnect(self.on_inventory_weight_updated)
        self.bot.inventory_signals.weight_max.disconnect(self.on_weight_max_updated)
        self.bank_panel.disconnect_signals()
        self.signals_connected = False
        self.items_by_uid.clear()
        self._rebuild_timer.stop()
        self.list_widget.clear()
        self.equipment_panel.set_items({})
        self.loading_label.hide()
        self.grid_container.set_placeholder("Inventory data has not been received yet.")

    def _resync_inventory(self) -> None:
        self.items_by_uid.clear()
        self.list_widget.clear()
        inventory = self.bot.game_state.inventory
        self.inventory_weight = inventory.inventory_weight
        self.weight_max = inventory.weight_max
        self._refresh_weight_label()
        self.on_added_object_items_batch(list(inventory.objects_by_uid.values()))

    def showEvent(self, a0: QShowEvent | None) -> None:
        if self._render_dirty:
            self._rebuild_sorted_list()
        super().showEvent(a0)
