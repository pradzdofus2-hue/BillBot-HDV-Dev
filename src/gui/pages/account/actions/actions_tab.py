from __future__ import annotations

from enum import StrEnum

from DBDofusUnity.dofus_unity_reader.models.datas.recipe_root import RecipeItem
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBox,
    FluentIcon,
    TransparentToolButton,
)

from src.controller.settings import SettingsService
from src.core.behaviors.behavior_factory import USABLE_BEHAVIORS
from src.gui.pages.account.actions.launch_summary_panel import LaunchSummaryPanel
from src.gui.pages.account.actions.world_map_panel import WorldMapPanel
from src.services.display_catalog import load_display_catalog
lazy from src.core.bot.bot import Bot
lazy from src.gui.pages.account.actions.craft.craft_panel import CraftPanel


class FarmActionEnum(StrEnum):
    AUTO = "Automatic"
    HARVESTER = "Harvester"
    FIGHTER = "Fighter"


class CraftActionEnum(StrEnum):
    CRAFTER = "Craft"


HDV_BEHAVIOR_LABELS = {
    "SaleHotelSellBehavior": "HDV - Vendre ressources",
    "SaleHotelUpdatePricesBehavior": "HDV - Actualiser prix",
}


class ActionsTab(QWidget):
    play_btn: TransparentToolButton
    stop_btn: TransparentToolButton
    type_action_combo: ComboBox
    area_farm_combo: ComboBox
    sub_area_farm_combo: ComboBox

    def __init__(
        self,
        bot: Bot,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.bot = bot
        self._v_layout = QVBoxLayout()
        self._v_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(self._v_layout)

        self.craft_panel: CraftPanel | None = None
        self._running = False

        self._catalog = load_display_catalog()
        self.world_map_panel = WorldMapPanel(bot.world_signals, self)
        self.launch_summary = LaunchSummaryPanel(self)
        self.init_top_content()

        self._v_layout.addWidget(self.launch_summary)
        self._v_layout.addWidget(self.world_map_panel, 1)

        self.bot.bot_signals.play_harvester.connect(self.on_play_harvester)
        self.bot.bot_signals.play_crafter.connect(self.on_play_craft)
        self.bot.bot_signals.play_auto_bot.connect(self.on_play_auto)
        self.bot.bot_signals.play_fighter.connect(self.on_play_fighter)
        self.bot.bot_signals.play_usable_behavior.connect(self.on_play_usable_behavior)
        self._sync_running_action()

    def init_top_content(self) -> None:
        top_widget = QWidget(self)
        top_widget_layout = QHBoxLayout()
        top_widget.setLayout(top_widget_layout)

        self.play_btn = TransparentToolButton(FluentIcon.PLAY, top_widget)
        self.play_btn.clicked.connect(self.on_click_play)
        self.bot.bot_signals.play.connect(self.on_play)
        top_widget_layout.addWidget(self.play_btn)

        self.stop_btn = TransparentToolButton(FluentIcon.PAUSE, top_widget)
        self.stop_btn.clicked.connect(self.bot.bot_signals.stop.emit)
        self.bot.bot_signals.stop.connect(self.on_stop)
        top_widget_layout.addWidget(self.stop_btn)
        self.stop_btn.hide()

        self.type_action_combo = ComboBox(top_widget)
        for farm_action in FarmActionEnum:
            self.type_action_combo.addItem(farm_action)

        self.type_action_combo.addItem(CraftActionEnum.CRAFTER)
        for usable_behavior in USABLE_BEHAVIORS:
            behavior_name = usable_behavior.__name__
            self.type_action_combo.addItem(
                HDV_BEHAVIOR_LABELS.get(behavior_name, behavior_name),
                userData=behavior_name,
            )

        self.type_action_combo.setCurrentText(FarmActionEnum.AUTO)
        self.type_action_combo.currentIndexChanged.connect(self.on_type_action_changed)
        top_widget_layout.addWidget(self.type_action_combo)

        self.sub_area_farm_combo = ComboBox(top_widget)
        self.sub_area_farm_combo.currentIndexChanged.connect(self.refresh_launch_summary)

        self.area_farm_combo = ComboBox(top_widget)
        self.area_farm_combo.addItem("")
        for area in self._catalog.areas:
            self.area_farm_combo.addItem(area.name, userData=area.id)
        self.area_farm_combo.currentIndexChanged.connect(self.on_area_selected)

        top_widget_layout.addWidget(self.area_farm_combo)

        top_widget_layout.addWidget(self.sub_area_farm_combo)

        self._v_layout.addWidget(top_widget)
        self.on_type_action_changed()

    @pyqtSlot()
    def on_type_action_changed(self) -> None:
        current_action = self.type_action_combo.currentText()
        show_zones = current_action in (FarmActionEnum.HARVESTER, FarmActionEnum.FIGHTER)
        self.area_farm_combo.setVisible(show_zones)
        self.sub_area_farm_combo.setVisible(show_zones)
        is_craft = current_action == CraftActionEnum.CRAFTER
        self.world_map_panel.setVisible(not is_craft)
        if is_craft:
            self._ensure_craft_panel()
        if self.craft_panel is not None:
            self.craft_panel.setVisible(is_craft)
            self.craft_panel.setEnabled(not self._running)
        self._refresh_play_button()
        self.refresh_launch_summary()

    def refresh_launch_summary(self) -> None:
        mode = self.type_action_combo.currentText()
        whole_area = False
        if mode == FarmActionEnum.AUTO:
            target = "Selected automatically at runtime"
        elif self.sub_area_farm_combo.currentData() is not None:
            target = self.sub_area_farm_combo.currentText()
        elif self.area_farm_combo.currentData() is not None:
            target = self.area_farm_combo.currentText()
            whole_area = True
        else:
            target = "Current subarea at startup"
        saved_settings = SettingsService().get().behaviors
        settings = self.bot.game_state.settings if self._running else saved_settings
        self.launch_summary.update_summary(
            mode, target, settings, running=self._running, whole_area=whole_area,
            pending_changes=self._running and settings != saved_settings,
        )

    def _ensure_craft_panel(self) -> CraftPanel:
        if self.craft_panel is None:
            self.craft_panel = CraftPanel(self.bot, self)
            self.craft_panel.queue_changed.connect(self._refresh_play_button)
            self._v_layout.insertWidget(2, self.craft_panel, 1)
        return self.craft_panel

    def _refresh_play_button(self) -> None:
        is_craft = self.type_action_combo.currentText() == CraftActionEnum.CRAFTER
        has_recipes = self.craft_panel is not None and bool(self.craft_panel.recipes)
        self.play_btn.setEnabled(not self._running and (not is_craft or has_recipes))

    @pyqtSlot()
    def on_area_selected(self) -> None:
        current_area_id = self.area_farm_combo.currentData()
        self.sub_area_farm_combo.clear()
        if current_area_id is None:
            self.refresh_launch_summary()
            return
        self.sub_area_farm_combo.addItem("")
        for sub_area in self._catalog.sub_areas.get(current_area_id, []):
            self.sub_area_farm_combo.addItem(sub_area.name, userData=sub_area.id)
        self.refresh_launch_summary()

    @pyqtSlot()
    def on_click_play(self) -> None:
        if self._running or not self.play_btn.isEnabled():
            return
        area_id = self.area_farm_combo.currentData()
        sub_area_id = self.sub_area_farm_combo.currentData()
        mode = self.type_action_combo.currentText()
        self.bot.bot_signals.play.emit(True)
        if mode == FarmActionEnum.HARVESTER:
            self.bot.bot_signals.play_harvester.emit(area_id, sub_area_id)
        elif mode == FarmActionEnum.FIGHTER:
            self.bot.bot_signals.play_fighter.emit(area_id, sub_area_id)
        elif mode == FarmActionEnum.AUTO:
            self.bot.bot_signals.play_auto_bot.emit()
        elif mode == CraftActionEnum.CRAFTER:
            self.bot.bot_signals.play_crafter.emit(self._ensure_craft_panel().recipes)
        else:
            behavior_name = self.type_action_combo.currentData() or mode
            self.bot.bot_signals.play_usable_behavior.emit(behavior_name)

    @pyqtSlot(bool)
    def on_play(self, _: bool) -> None:
        self._running = True
        self.stop_btn.show()
        self.play_btn.hide()
        self.type_action_combo.setDisabled(True)
        self.area_farm_combo.setDisabled(True)
        self.sub_area_farm_combo.setDisabled(True)
        if self.craft_panel is not None:
            self.craft_panel.setEnabled(False)
        self.refresh_launch_summary()

    @pyqtSlot(object, object)
    def on_play_harvester(self, area_id: int | None, sub_area_id: int | None) -> None:
        self.type_action_combo.setCurrentText(FarmActionEnum.HARVESTER)
        self.on_played_zone(area_id, sub_area_id)

    @pyqtSlot(object, object)
    def on_play_fighter(self, area_id: int | None, sub_area_id: int | None) -> None:
        self.type_action_combo.setCurrentText(FarmActionEnum.FIGHTER)
        self.on_played_zone(area_id, sub_area_id)

    @pyqtSlot()
    def on_play_auto(self) -> None:
        self.type_action_combo.setCurrentText(FarmActionEnum.AUTO)
        self.refresh_launch_summary()

    @pyqtSlot(object)
    def on_play_craft(self, recipes: list[RecipeItem]) -> None:
        page = self._ensure_craft_panel()
        page.set_recipes(recipes)
        self.type_action_combo.setCurrentText(CraftActionEnum.CRAFTER)
        page.setEnabled(not self._running)

    @pyqtSlot(str)
    def on_play_usable_behavior(self, name: str) -> None:
        index = self.type_action_combo.findData(name)
        if index >= 0:
            self.type_action_combo.setCurrentIndex(index)
        else:
            self.type_action_combo.setCurrentText(name)

    def on_played_zone(self, area_id: int | None, sub_area_id: int | None) -> None:
        if area_id is not None:
            self.area_farm_combo.setCurrentIndex(self.area_farm_combo.findData(area_id))
        else:
            self.area_farm_combo.setCurrentText("")

        if sub_area_id is not None:
            self.sub_area_farm_combo.setCurrentIndex(self.sub_area_farm_combo.findData(sub_area_id))
        else:
            self.sub_area_farm_combo.setCurrentText("")
        self.refresh_launch_summary()

    @pyqtSlot()
    def on_stop(self) -> None:
        self.play_btn.show()
        self.stop_btn.hide()
        self._running = False
        self.type_action_combo.setDisabled(False)
        self.area_farm_combo.setDisabled(False)
        self.sub_area_farm_combo.setDisabled(False)
        self.on_type_action_changed()

    def _sync_running_action(self) -> None:
        if not self.bot.is_playing_event.is_set():
            return
        activity = self.bot.behavior_coordinator
        labels = {
            "auto": FarmActionEnum.AUTO,
            "harvest": FarmActionEnum.HARVESTER,
            "fight": FarmActionEnum.FIGHTER,
            "craft": CraftActionEnum.CRAFTER,
        }
        action_label = labels.get(activity.action_name, activity.action_name)
        behavior_index = self.type_action_combo.findData(activity.action_name)
        if behavior_index >= 0:
            self.type_action_combo.setCurrentIndex(behavior_index)
        else:
            self.type_action_combo.setCurrentText(action_label)
        if activity.action_name in ("harvest", "fight"):
            self.on_played_zone(activity.area_id, activity.sub_area_id)
        self.on_play(False)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self._sync_running_action()
        self.refresh_launch_summary()
