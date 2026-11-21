from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget

from src.core.config import BehaviorSettings


class LaunchSummaryPanel(CardWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        self.title_label = BodyLabel(parent=self)
        self.description_label = CaptionLabel(parent=self)
        self.target_label = CaptionLabel(parent=self)
        self.enabled_label = CaptionLabel(parent=self)
        self.scheduled_label = CaptionLabel(parent=self)
        self.pending_label = CaptionLabel(parent=self)
        for label in (
            self.title_label, self.description_label, self.target_label,
            self.enabled_label, self.scheduled_label, self.pending_label,
        ):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)

    def update_summary(
        self,
        mode: str,
        target: str,
        settings: BehaviorSettings,
        *,
        running: bool,
        whole_area: bool,
        pending_changes: bool = False,
    ) -> None:
        match mode:
            case "Automatic":
                description = (
                    "Harvest resources, choose farming areas automatically, "
                    "and adapt to inventory conditions."
                )
            case "Harvester":
                description = "Harvest available resources along a farming route."
            case "Fighter":
                description = "Fight monster groups along a farming route."
            case _:
                self.hide()
                return

        self.show()
        self.title_label.setText("Running mode" if running else "Launch summary")
        self.description_label.setText(description)
        target_text = f"Target: {target}"
        if whole_area:
            target_text += " — Subareas are filtered by character level."
        self.target_label.setText(target_text)

        enabled: list[str] = []
        if mode == "Automatic" and settings.do_fighter:
            enabled.append("Automatic combat")
        if settings.do_use_guild_chest:
            enabled.append("Guild chest")
        if settings.enable_auto_equipment_market_purchases:
            enabled.append("Equipment purchases")
        self.enabled_label.setText(
            "Enabled when needed: " + " · ".join(enabled) if enabled else ""
        )
        self.enabled_label.setVisible(bool(enabled))

        scheduled: list[str] = []
        if mode == "Automatic":
            if settings.do_sale_hotel:
                scheduled.append("Marketplace sales")
            if settings.do_craft:
                scheduled.append("Automatic crafting")
            if settings.do_dungeon:
                scheduled.append("Dungeons")
            if settings.do_idle:
                scheduled.append("Idle breaks")
        self.scheduled_label.setText(
            "Scheduled sessions: " + " · ".join(scheduled)
            + "\nRun when due in a scheduled session."
            if scheduled else ""
        )
        self.scheduled_label.setVisible(bool(scheduled))
        self.pending_label.setText("Updated settings will apply at the next startup.")
        self.pending_label.setVisible(pending_changes)
