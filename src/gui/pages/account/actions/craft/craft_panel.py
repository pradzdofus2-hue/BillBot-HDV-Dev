from __future__ import annotations

lazy from src.core.bot.bot import Bot

from DBDofusUnity.dofus_unity_reader.models.datas.recipe_root import RecipeItem
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from src.gui.pages.account.actions.craft.recipe_search_panel import RecipeSearchPanel
from src.gui.pages.account.actions.craft.craft_queue_table import CraftQueueTable


class CraftPanel(QWidget):
    queue_changed = pyqtSignal()

    def __init__(self, bot: Bot, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)

        self.bot = bot
        self.main_layout = QVBoxLayout()
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignCenter)
        self.setLayout(self.main_layout)

        self.craft_queue_table = CraftQueueTable(recipes=[], parent=self)
        self.recipe_search_panel = RecipeSearchPanel(parent=self)

        self.recipe_search_panel.signals.clicked_elem_queue.connect(self.on_added_recipe_queue)
        self.craft_queue_table.signals.removed_recipe.connect(self.on_removed_recipe_queue)

        self.main_layout.addWidget(self.craft_queue_table)
        self.main_layout.addWidget(self.recipe_search_panel)

    @pyqtSlot(object)
    def on_removed_recipe_queue(self, recipe: RecipeItem):
        self.recipe_search_panel.add_item(recipe)
        self.queue_changed.emit()

    @pyqtSlot(object)
    def on_added_recipe_queue(self, recipe: RecipeItem):
        self.recipe_search_panel.remove_item(recipe)
        self.craft_queue_table.add_recipe(recipe)
        self.bot.logger.info(f"Added recipe for result {recipe.resultId}")
        self.queue_changed.emit()

    @property
    def recipes(self) -> list[RecipeItem]:
        return list(self.craft_queue_table.recipes)

    def set_recipes(self, recipes: list[RecipeItem]) -> None:
        if recipes == self.recipes:
            return
        for recipe in self.recipes:
            self.recipe_search_panel.add_item(recipe)
        model = self.craft_queue_table.table.item_model
        model.clear_all()
        self.craft_queue_table.widget_item_by_recipe.clear()
        for recipe in recipes:
            self.craft_queue_table.add_recipe(recipe)
            self.recipe_search_panel.remove_item(recipe)
        self.queue_changed.emit()
