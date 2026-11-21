from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Literal

from PyQt6.QtCore import QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    NavigationItemPosition,
)
lazy from ankama_launcher_emulator.controller.bot_storage import BotStorageController

from src.consts import LOGO_FILE, MIN_DATE
from src.controller.bot_config import BotConfig, BotConfigService
from src.controller.player_info_storage import PlayerInfoSnapshot, PlayerInfoStorage
from src.core.signals.log_signals import LogSignals
from src.core.signals.shared_farm_signals import SharedSignals
from src.gui.components.manual_confirmation import ManualConfirmationDialogs
from src.gui.consts import BASE_HEIGHT, BASE_WIDTH
from src.gui.fragments.app_fluent_window import AppFluentWindow
from src.gui.fragments.sidebar_item import SidebarItem
from src.gui.services.item_icons import class_icon_cache
from src.gui.pages.activity_page import ActivityPage
from src.gui.pages.settings.settings_page import SettingsPage
from src.gui.pages.startup_page import StartupPage
from src.services.background import run_in_background
from src.services.logging_utils.loggers import init_root_gui_logging
lazy from src.core.bot.bot import Bot
lazy from src.core.bot.bot_manager import BotManager
lazy from src.gui.pages.account.account_page import AccountPage
lazy from src.services.startup import subscription_end_dates

class MainWindow(AppFluentWindow):
    retry_requested = pyqtSignal()
    account_widgets: list[AccountPage]
    bots_by_login: dict[str, Bot]
    sidebar_items_by_login: dict[str, SidebarItem]

    def __init__(self, title: str, shared_signals: SharedSignals) -> None:
        super().__init__(parent=None)

        self.global_log_signals = LogSignals()
        init_root_gui_logging(self.global_log_signals)

        self.title = title
        self.shared_signals = shared_signals
        self.setWindowTitle(self.title)
        self.resize(BASE_WIDTH, BASE_HEIGHT)
        self.setWindowIcon(QIcon(LOGO_FILE))
        self.startup_page = StartupPage(self)
        self.startup_page.retry_requested.connect(self.retry_requested.emit)
        self.stackedWidget.addWidget(self.startup_page)

        self.disconnected_icon = FluentIcon.PEOPLE.icon(color=QColor(255, 0, 0))
        self.connected_icon = FluentIcon.PEOPLE.icon(color=QColor(0, 255, 0))
        self._class_icons = class_icon_cache()
        self._class_icons.ready.connect(self._on_breed_icon_ready)

        self.account_widgets: list[AccountPage] = []
        self._account_pages: dict[str, QWidget] = {}
        self._account_details: dict[str, tuple[PlayerInfoSnapshot | None, str | None, datetime]] = {}
        self._runtime_ready = False
        self.bots_by_login: dict[str, Bot] = {}
        self.sidebar_items_by_login: dict[str, SidebarItem] = {}
        self._subscription_refresh_timer = QTimer(self)
        self._subscription_refresh_timer.setInterval(60_000)
        self._subscription_refresh_timer.timeout.connect(self._refresh_subscription_statuses)

        self._close_requested = False
        self._shutdown_finished = False
        self.shared_signals.new_bot_added.connect(self.add_account)
        self.shared_signals.bot_removed.connect(self.remove_account)
        self.activity_page = ActivityPage(parent=self)
        self.activity_page.set_actions_enabled(False)
        self.stackedWidget.addWidget(self.activity_page)
        self.navigationInterface.addItem(
            routeKey=self.activity_page.objectName(),
            icon=FluentIcon.HISTORY,  # type: ignore
            text="Activity",
            onClick=lambda: self.switchTo(self.activity_page),
            position=NavigationItemPosition.TOP,
        )
        self.navigationInterface.setCurrentItem(self.activity_page.objectName())
        self.settings_page = SettingsPage(self)
        self.settings_page.setEnabled(False)
        self.stackedWidget.addWidget(self.settings_page)
        self.navigationInterface.addItem(
            routeKey="settings",
            icon=FluentIcon.SETTING,
            text="Settings",
            onClick=lambda: self.switchTo(self.settings_page),
            position=NavigationItemPosition.BOTTOM,
        )
        self.settings_page.schedules_changed.connect(self._refresh_schedules)
        self.settings_page.behaviors_changed.connect(self._refresh_launch_summaries)
        self.confirmation_dialogs = ManualConfirmationDialogs(self)
        self.navigationInterface.hide()
        self.update_title_bar_geometry()
        self.stackedWidget.setCurrentWidget(self.startup_page)

    def _refresh_launch_summaries(self) -> None:
        for page in self.account_widgets:
            page.actions_tab.refresh_launch_summary()

    def _refresh_schedules(self) -> None:
        if not BotConfigService.use_bot_config_json:
            return
        bots = list(self.bots_by_login.values())

        def refresh(_progress: Callable[[str], None]) -> None:
            for bot in bots:
                bot.scheduler.request_configuration_refresh()

        run_in_background(refresh)

    def set_startup_status(self, status: str) -> None:
        self.startup_page.show_status(status)

    def show_startup_error(self, message: str) -> None:
        self.startup_page.show_status(message, error=True)

    def set_runtime_ready(self) -> None:
        if self._runtime_ready:
            return
        self._runtime_ready = True
        self.navigationInterface.show()
        self.update_title_bar_geometry()
        self.switchTo(self.activity_page)
        self.navigationInterface.setCurrentItem(self.activity_page.objectName())
        self.settings_page.enable_editing()
        self.activity_page.set_actions_enabled(True)
        for sidebar in self.sidebar_items_by_login.values():
            sidebar.set_controls_enabled(True)
        for view in self.account_widgets:
            view.setEnabled(True)
        self._subscription_refresh_timer.start()

    def bind_runtime(self, manager: BotManager) -> None:
        self.activity_page.restore_account_requested.connect(manager.restore_account_from_quarantine)
        self.activity_page.delete_account_requested.connect(manager.delete_account)
        self.activity_page.restore_mailbox_requested.connect(manager.restore_mailbox_from_quarantine)
        self.activity_page.delete_mailbox_requested.connect(manager.delete_mailbox)
        self.settings_page.bind_account_actions(
            manager.delete_account, manager.delete_mailbox, self.activity_page.refresh
        )

    def unbind_runtime(self, manager: BotManager) -> None:
        self.activity_page.restore_account_requested.disconnect(manager.restore_account_from_quarantine)
        self.activity_page.delete_account_requested.disconnect(manager.delete_account)
        self.activity_page.restore_mailbox_requested.disconnect(manager.restore_mailbox_from_quarantine)
        self.activity_page.delete_mailbox_requested.disconnect(manager.delete_mailbox)
        manager.disconnect_signals()

    def clear_accounts(self) -> None:
        for account in list(self.bots_by_login.values()):
            self.remove_account(account)
        self._runtime_ready = False
        self.settings_page.setEnabled(False)
        self.activity_page.set_actions_enabled(False)
        self._subscription_refresh_timer.stop()

    def switchTo(self, widget: QWidget) -> None:
        if not self._runtime_ready:
            return
        login = widget.objectName()
        if login in self.bots_by_login and widget.layout() is None:
            snapshot, reason, subscription_end = self._account_details[login]
            view = AccountPage(
                self.global_log_signals,
                login,
                self.bots_by_login[login],
                snapshot,
                reason,
                parent=widget,
                subscription_end=subscription_end,
            )
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(view)
            view.setEnabled(self._runtime_ready)
            self.account_widgets.append(view)
        super().switchTo(widget)

    def add_account(
        self,
        account: Bot,
        snapshot: PlayerInfoSnapshot | None = None,
        quarantine_reason: str | None = None,
        bot_config: BotConfig | None = None,
        subscription_end: datetime = MIN_DATE,
    ) -> None:
        login = account.account.apikey.login
        self.bots_by_login[login] = account

        account_widget = QWidget(self.stackedWidget)
        self._account_pages[login] = account_widget
        self._account_details[login] = (snapshot, quarantine_reason, subscription_end)
        navigation_widget = SidebarItem(account.bot_signals, self.disconnected_icon, login, True, parent=self)
        self._set_sidebar_title(navigation_widget, login, snapshot)
        self.sidebar_items_by_login[login] = navigation_widget
        navigation_widget.set_controls_enabled(self._runtime_ready)
        navigation_widget.set_playing(account.is_playing_event.is_set())
        navigation_widget.set_subscribed(subscription_end > datetime.now(tz=subscription_end.tzinfo))
        is_connected = account.is_connected_event.is_set()
        navigation_widget.set_connected(is_connected)
        if is_connected:
            navigation_widget.set_left_icon(self.connected_icon)
        account_widget.setObjectName(login)
        self.addWidget(
            account_widget,
            navigation_widget,
            position=NavigationItemPosition.SCROLL,
        )
        if len(self.bots_by_login) == 1:
            self.navigationInterface.panel.expand(useAni=False)

        selected_mode = (
            bot_config if bot_config is not None else BotConfigService().get_bot_config(login)
        ).connection_mode
        navigation_widget.populate_connection_mode(selected_mode)
        if bot_config is None:
            self._refresh_subscription_statuses()

        def on_connection_mode_changed(mode: str) -> None:
            assert mode in ("mitm", "socket"), f"Unknown connection mode {mode}"
            self._on_connection_mode_changed(login, mode)

        navigation_widget.connection_mode_changed.connect(on_connection_mode_changed)
        navigation_widget.disconnect_clicked.connect(lambda: self._on_disconnect_clicked(login))

        def on_connected(_characters: object) -> None:
            navigation_widget.set_left_icon(self.connected_icon)
            navigation_widget.set_connected(True)

        account.game_info_signals.connected.connect(on_connected)

        def on_character_name(name: str) -> None:
            navigation_widget.set_title(f"{account.account.apikey.login.split('@')[0]} : {name}")

        account.game_info_signals.character_name.connect(on_character_name)

        account.game_info_signals.in_fight.connect(navigation_widget.show_battle_icon)
        account.game_info_signals.is_ready_to_play.connect(
            partial(self._show_breed_icon, navigation_widget, account)
        )
        account.game_info_signals.disconnected.connect(
            lambda: navigation_widget.set_left_icon(self.disconnected_icon)
        )
        account.game_info_signals.disconnected.connect(lambda: navigation_widget.set_connected(False))
        account.game_info_signals.disconnected.connect(
            partial(self._set_sidebar_title_from_storage, navigation_widget, login)
        )

        if account.is_ready_to_play_event.is_set():
            self._show_breed_icon(navigation_widget, account)

    @staticmethod
    def _set_sidebar_title(
        navigation_widget: SidebarItem,
        login: str,
        snapshot: PlayerInfoSnapshot | None,
    ) -> None:
        if snapshot is None:
            navigation_widget.set_title(login)
            return
        navigation_widget.set_title(f"{login.split('@')[0]} : {snapshot.character_name}")

    def _set_sidebar_title_from_storage(self, navigation_widget: SidebarItem, login: str) -> None:
        self._set_sidebar_title(navigation_widget, login, PlayerInfoStorage().get_snapshot(login))

    def _show_breed_icon(self, navigation_widget: SidebarItem, account: Bot) -> None:
        if not account.is_connected_event.is_set():
            navigation_widget.set_left_icon(self.disconnected_icon)
            return
        navigation_widget.set_left_icon(self.connected_icon)
        breed_id = account.game_state.fight.breed_id
        if breed_id <= 0:
            return
        image = self._class_icons.request(breed_id)
        if image is not None:
            navigation_widget.set_left_icon(QIcon(QPixmap.fromImage(image)))

    @pyqtSlot(int, QImage)
    def _on_breed_icon_ready(self, breed_id: int, image: QImage) -> None:
        icon = QIcon(QPixmap.fromImage(image))
        for login, account in self.bots_by_login.items():
            if (
                account.is_connected_event.is_set()
                and account.is_ready_to_play_event.is_set()
                and account.game_state.fight.breed_id == breed_id
            ):
                self.sidebar_items_by_login[login].set_left_icon(icon)

    def remove_account(self, account: Bot) -> None:
        login = account.account.apikey.login
        self.bots_by_login.pop(login, None)
        self.sidebar_items_by_login.pop(login)
        self._disconnect_game_info_signals(account)

        page = self._account_pages.pop(login)
        self._account_details.pop(login)
        self.account_widgets = [widget for widget in self.account_widgets if widget.login != login]
        self.removeWidget(login, page)
        page.deleteLater()

    def _refresh_subscription_statuses(self) -> None:
        run_in_background(
            lambda _: subscription_end_dates(BotStorageController().get_all_records()),
            on_success=self._set_subscription_statuses,
        )

    def _set_subscription_statuses(self, dates: dict[str, datetime | None]) -> None:
        for login, account in self.bots_by_login.items():
            end = dates.get(login) or MIN_DATE
            self.sidebar_items_by_login[login].set_subscribed(end > datetime.now(tz=end.tzinfo))
            snapshot, reason, _ = self._account_details[login]
            self._account_details[login] = snapshot, reason, end
            account.game_info_signals.subscription_end_date.emit(end)

    def _disconnect_game_info_signals(self, account: Bot) -> None:
        for signal in (
            account.game_info_signals.connected,
            account.game_info_signals.character_name,
            account.game_info_signals.in_fight,
            account.game_info_signals.is_ready_to_play,
            account.game_info_signals.disconnected,
        ):
            try:
                signal.disconnect()
            except TypeError:
                pass

    def _on_connection_mode_changed(self, login: str, mode: Literal["mitm", "socket"]) -> None:
        BotConfigService().assign_mode(login, mode)

    def _on_disconnect_clicked(self, login: str) -> None:
        bot = self.bots_by_login[login]
        if not bot.is_connected_event.is_set():
            return
        bot.scheduler.disconnect_now()

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        if self._shutdown_finished:
            super().closeEvent(a0)
            return

        if a0 is not None:
            a0.ignore()
        if self._close_requested:
            return

        self._close_requested = True
        self._subscription_refresh_timer.stop()
        self.confirmation_dialogs.shutdown()
        self.setEnabled(False)
        self.shared_signals.closed.emit()

    def complete_shutdown(self) -> None:
        self._shutdown_finished = True
        self.close()
