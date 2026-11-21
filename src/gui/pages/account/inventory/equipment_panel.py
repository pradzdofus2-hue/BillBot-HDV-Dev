from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QListWidgetItem, QWidget
from qfluentwidgets import BodyLabel
from DBDofusUnity.datas.protos.non_obf.game.common_pb2 import ObjectItemInventory
from DBDofusUnity.dofus_unity_reader.game_constants.inventory_position import CharacterInventoryPositionEnum
from src.gui.components.group_box import GroupBox
from src.gui.components.item_grid import CELL_SIZE, ItemGrid

_SLOT_LAYOUT: list[tuple[CharacterInventoryPositionEnum, str, int]] = [
    (CharacterInventoryPositionEnum.AccessoryPositionHat, "Hat", 0),
    (CharacterInventoryPositionEnum.AccessoryPositionCape, "Cape", 3),
    (CharacterInventoryPositionEnum.AccessoryPositionWeapon, "Weapon", 9),
    (CharacterInventoryPositionEnum.AccessoryPositionShield, "Shield", 12),
    (CharacterInventoryPositionEnum.AccessoryPositionPets, "Pet", 14),
    (CharacterInventoryPositionEnum.InventoryPositionMount, "Mount", 15),
    (CharacterInventoryPositionEnum.AccessoryPositionAmulet, "Amulet", 2),
    (CharacterInventoryPositionEnum.InventoryPositionRingLeft, "Left ring", 6),
    (CharacterInventoryPositionEnum.InventoryPositionRingRight, "Right ring", 8),
    (CharacterInventoryPositionEnum.AccessoryPositionBelt, "Belt", 5),
    (CharacterInventoryPositionEnum.AccessoryPositionBoots, "Boots", 11),
    (CharacterInventoryPositionEnum.InventoryPositionDofus1, "Dofus 1", 18),
    (CharacterInventoryPositionEnum.InventoryPositionDofus2, "Dofus 2", 19),
    (CharacterInventoryPositionEnum.InventoryPositionDofus3, "Dofus 3", 20),
    (CharacterInventoryPositionEnum.InventoryPositionDofus4, "Dofus 4", 21),
    (CharacterInventoryPositionEnum.InventoryPositionDofus5, "Dofus 5", 22),
    (CharacterInventoryPositionEnum.InventoryPositionDofus6, "Dofus 6", 23),
]


class EquipmentPanel(GroupBox):
    def __init__(self, parent: QWidget | None = None):
        super().__init__("", parent=parent)
        title = BodyLabel(text="Equipment", parent=self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(title)
        self.list_widget = ItemGrid(self)
        self.list_widget.setSpacing(0)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setFixedSize(3 * CELL_SIZE + 1, 8 * CELL_SIZE + 1)
        self.setFixedWidth(self.list_widget.width())
        self.content_layout.addWidget(self.list_widget)
        self.content_layout.addStretch(1)
        self.set_items({})

    def set_items(self, items_by_position: dict[int, ObjectItemInventory]) -> None:
        self.list_widget.setUpdatesEnabled(False)
        self.list_widget.clear()
        for position, label, cell in sorted(_SLOT_LAYOUT, key=lambda slot: slot[2]):
            while self.list_widget.count() < cell:
                spacer = QListWidgetItem()
                spacer.setSizeHint(QSize(CELL_SIZE, CELL_SIZE))
                spacer.setData(Qt.ItemDataRole.UserRole + 2, True)
                spacer.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list_widget.addItem(spacer)
            object_item = items_by_position.get(int(position))
            if object_item is None:
                item = QListWidgetItem(label)
                item.setSizeHint(QSize(CELL_SIZE, CELL_SIZE))
                item.setToolTip(label)
                self.list_widget.addItem(item)
            else:
                item = self.list_widget.add_object_item(object_item)
                item.setToolTip(f"{label}\n{item.text()}")
        self.list_widget.setUpdatesEnabled(True)
