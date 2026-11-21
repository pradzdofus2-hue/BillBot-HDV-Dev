from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import cast

from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import SegmentedWidget

from src.consts import MIN_DATE
from src.controller.player_info_storage import PlayerInfoSnapshot
from src.core.signals.log_signals import LogSignals
from src.gui.pages.account.account_summary import AccountSummary
from src.gui.pages.account.actions.actions_tab import ActionsTab
lazy from src.core.bot.bot import Bot
lazy from src.gui.pages.account.debug.debug_tab import DebugTab
lazy from src.gui.pages.account.inventory.inventory_tab import InventoryTab
lazy from src.gui.pages.account.character.character_tab import CharacterTab


class AccountPage(QWidget):
    def __init__(
        self,
        global_log_signals: LogSignals,
        login: str,
        bot: Bot,
        snapshot: PlayerInfoSnapshot | None,
        quarantine_reason: str | None,
        parent: QWidget | None = None,
        subscription_end: datetime = MIN_DATE,
    ) -> None:
        super().__init__(parent=parent)
        self.login = login
        self.bot = bot
        self.setObjectName(f"{login}_bot")
        layout = QVBoxLayout(self)
        self.quick_info_widget = AccountSummary(
            bot, snapshot, quarantine_reason, parent=self, subscription_end=subscription_end
        )
        layout.addWidget(self.quick_info_widget)

        self.pivot = SegmentedWidget(self)
        layout.addWidget(self.pivot)
        self.stacked_widget = QStackedWidget(self)
        layout.addWidget(self.stacked_widget, 1)

        self.actions_tab = ActionsTab(bot, self.stacked_widget)
        self.stacked_widget.addWidget(self.actions_tab)
        self._tabs: dict[str, QWidget] = {"Actions": self.actions_tab}
        self._storage_tab: InventoryTab | None = None
        self._factories: dict[str, Callable[[], QWidget]] = {
            "Actions": lambda: self.actions_tab,
            "Character": lambda: CharacterTab(bot, self.stacked_widget, snapshot=snapshot),
            "Inventory": lambda: InventoryTab(bot, self.stacked_widget),
            "Debug": lambda: DebugTab(bot, global_log_signals, parent=self.stacked_widget),
        }
        for label in self._factories:
            item = self.pivot.addItem(
                routeKey=label,
                text=label,
                onClick=lambda _checked=False, label=label: self._select_tab(label),
            )
            if item is None:
                raise ValueError(f"Segmented route `{label}` is already registered")
            item.setFixedHeight(40)
        self.pivot.setCurrentItem("Actions")
        self._select_tab("Actions")

    def _select_tab(self, label: str) -> None:
        if self._storage_tab is not None:
            self._storage_tab.disconnect_signals()
            self._storage_tab = None
        if label not in self._tabs:
            widget = self._factories[label]()
            self._tabs[label] = widget
            self.stacked_widget.addWidget(widget)
        widget = self._tabs[label]
        self.stacked_widget.setCurrentWidget(widget)
        if label == "Inventory":
            self._storage_tab = cast(InventoryTab, widget)
            self._storage_tab.connect_signals()
