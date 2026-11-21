from __future__ import annotations

lazy from src.core.bot.bot import Bot
lazy from src.controller.player_info_storage import PlayerInfoSnapshot

from functools import partial

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from src.gui.components.graphics.grid_widget import GridView
from src.gui.components.qfluent_widget.scrollable_message_box import (
    ScrollableMessageBox,
)
from src.gui.pages.account.character.player_info_panel import PlayerInfoPanel
from src.services.display_catalog import load_display_catalog


class CharacterTab(QWidget):
    def __init__(
        self,
        bot: Bot,
        parent: QWidget | None = None,
        *,
        snapshot: PlayerInfoSnapshot | None = None,
    ):
        super().__init__(parent=parent)
        self.grid_signals = bot.grid_signals
        self.game_info_signals = bot.game_info_signals
        self.game_state = bot.game_state
        self._catalog = load_display_catalog()

        layout = QHBoxLayout(self)
        grid_view = GridView(self.grid_signals)
        grid_view.on_new_map_id(self.game_state.map.map_id)
        grid_view.on_new_count_actor_on_cell_id_batch(
            [(point.cell_id, len(actors)) for point, actors in self.game_state.entity.actors_on_mp.items()]
        )
        grid_view.on_set_obstacle_on_cell_id_batch(
            [(cell_id, True) for cell_id in self.game_state.entity.obstacle_on_cell_id]
        )
        grid_view.on_set_stated_element_on_cell_id_batch(
            [
                (stated_element.cell_id, stated_element, collectable)
                for stated_element, collectable in self.game_state.interactive.stated_element_by_id.values()
            ]
        )
        layout.addWidget(grid_view, 1)

        self.info_panel = PlayerInfoPanel(bot, parent=self, snapshot=snapshot)
        self.info_panel.setMinimumWidth(300)
        self.info_panel.setMaximumWidth(360)
        layout.addWidget(self.info_panel)
        self.info_panel.pre_create_group("Map")
        self._connect_info_signals()
        self.on_in_fight_changed(self.game_state.fight.in_fight)
        self.info_panel.on_received_property("Map", "Transition in progress", bool(self.game_state.map.is_in_map_transition))
        self.info_panel.on_received_property("Map", "In Haven Bag", self.game_state.map.is_in_haven_bag)

        self.grid_signals.cell_id_clicked.connect(self.on_cell_id_clicked)

        if self.game_state.map.map_id != 0:
            self.on_map_id_changed(self.game_state.map.map_id)

    def _connect_info_signals(self) -> None:
        self.grid_signals.new_map_id.connect(self.on_map_id_changed)
        self.grid_signals.is_in_map_transition.connect(
            partial(self.info_panel.on_received_property, "Map", "Transition in progress")
        )
        self.game_info_signals.is_in_haven_bag.connect(
            partial(self.info_panel.on_received_property, "Map", "In Haven Bag")
        )

        self.combat_group = self.info_panel.pre_create_group("Combat")
        self.combat_group.set_active(False)
        self.game_info_signals.in_fight.connect(self.on_in_fight_changed)
        self.game_info_signals.is_our_turn.connect(
            partial(self.info_panel.on_received_property, "Combat", "Our turn")
        )
        self.game_info_signals.life_point.connect(
            partial(self.info_panel.on_received_property, "Combat", "Health")
        )
        self.game_info_signals.max_life_point.connect(
            partial(self.info_panel.on_received_property, "Combat", "Maximum health")
        )
        self.game_info_signals.action_points.connect(
            partial(self.info_panel.on_received_property, "Combat", "AP")
        )
        self.game_info_signals.movement_points.connect(
            partial(self.info_panel.on_received_property, "Combat", "MP")
        )

    @pyqtSlot(bool)
    def on_in_fight_changed(self, in_fight: bool) -> None:
        self.combat_group.set_active(in_fight)

    @pyqtSlot(int)
    def on_map_id_changed(self, map_id: int) -> None:
        self.info_panel.on_received_property("Map", "ID", map_id)
        position = self._catalog.map_positions[map_id]
        self.info_panel.on_received_property("Map", "Coordinates", str(position))

    @pyqtSlot(int)
    def on_cell_id_clicked(self, cell_id: int) -> None:
        actor = self.game_state.entity.get_first_actor_on_cell_id(cell_id)

        if actor is not None:
            if actor.actor_id in self.game_state.entity.actor_fight_by_id:
                content = str(self.game_state.entity.actor_fight_by_id[actor.actor_id])
            else:
                content = str(actor)
            ScrollableMessageBox(f"Actor on cell {cell_id}", content, self).exec()
            return

        stated_elements = self.game_state.interactive.stated_element_by_cell_id.get(cell_id)
        if stated_elements:
            stated_element, collectable = next(iter(stated_elements.values()))
            content = str(stated_element)
            if collectable is not None:
                content += f"\n\nCollectable: {collectable}"
            ScrollableMessageBox(f"Interactive on cell {cell_id}", content, self).exec()
