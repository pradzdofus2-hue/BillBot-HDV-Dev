"""Per-account, read-only craft shopping list powered by existing bank/inventory frames."""
from __future__ import annotations

from threading import Thread

from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.engine.crafts.material_planner import compare_materials, craft_requirements
from src.services.display_catalog import load_display_catalog
from src.services.dofusbook_atelier import (
    fetch_public_atelier,
    normalize_item_name,
    parse_atelier_text,
    require_accessible_atelier,
)
lazy from src.core.bot.bot import Bot


class CraftAtelierPage(QWidget):
    """Shows material requirements; never executes purchases or bank transfers."""

    url_imported = pyqtSignal(str, str)

    def __init__(self, bot: Bot, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bot = bot
        self.catalog = load_display_catalog()
        self.crafts: dict[int, int] = {}
        self.external_requirements: dict[int, int] = {}
        self.using_dofusbook = False
        self._gid_by_name: dict[str, int] | None = None
        self._names_by_gid: dict[int, str] = {}
        self._importing = False
        self._missing_text = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("Atelier de craft — Dofusbook + Banque / Inventaire", self)
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(title)

        self.status = QLabel(
            "Les quantités viennent des derniers scans du personnage. "
            "Ouvre la banque en jeu au moins une fois pour la synchroniser.",
            self,
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addWidget(QLabel("1. Ajouter un équipement ou une recette locale", self))
        craft_row = QHBoxLayout()
        self.item_edit = QLineEdit(self)
        self.item_edit.setPlaceholderText("Nom de l'objet (ex. Coiffe du Bouftou)")
        recipe_names = sorted(entry.name for entry in self.catalog.recipe_by_id.values())
        completer = QCompleter(recipe_names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.item_edit.setCompleter(completer)
        craft_row.addWidget(self.item_edit, 1)
        self.amount = QSpinBox(self)
        self.amount.setRange(1, 9999)
        self.amount.setValue(1)
        self.amount.setToolTip("Nombre d'exemplaires à fabriquer")
        craft_row.addWidget(self.amount)
        add_button = QPushButton("Ajouter", self)
        add_button.clicked.connect(self._add_craft)
        craft_row.addWidget(add_button)
        layout.addLayout(craft_row)

        craft_list_row = QHBoxLayout()
        self.craft_list = QListWidget(self)
        self.craft_list.setMaximumHeight(78)
        craft_list_row.addWidget(self.craft_list, 1)
        remove_button = QPushButton("Retirer", self)
        remove_button.clicked.connect(self._remove_craft)
        craft_list_row.addWidget(remove_button)
        layout.addLayout(craft_list_row)

        layout.addWidget(QLabel("2. Ou importer les ressources depuis un atelier Dofusbook public", self))
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("https://www.dofusbook.net/mobile/fr/membre/.../atelier")
        url_row.addWidget(self.url_edit, 1)
        self.url_button = QPushButton("Lire le lien", self)
        self.url_button.clicked.connect(self._import_url)
        url_row.addWidget(self.url_button)
        layout.addLayout(url_row)

        self.pasted_text = QPlainTextEdit(self)
        self.pasted_text.setPlaceholderText(
            "Dans Chrome, ouvre l'atelier Dofusbook, sélectionne la liste "
            "visible (Ctrl+A, Ctrl+C), puis clique « Importer le presse-papiers ». "
            "Ne copie pas le code source HTML. Aucun identifiant requis."
        )
        self.pasted_text.setMaximumHeight(65)
        layout.addWidget(self.pasted_text)
        paste_row = QHBoxLayout()
        paste_button = QPushButton("Importer le texte copié", self)
        paste_button.clicked.connect(self._import_pasted_text)
        paste_row.addWidget(paste_button)
        clipboard_button = QPushButton("Importer le presse-papiers (Chrome)", self)
        clipboard_button.setToolTip(
            "Copie la liste des ingrédients visible dans Chrome (Ctrl+C), "
            "puis clique ici pour l'analyser localement."
        )
        clipboard_button.clicked.connect(self._import_clipboard)
        paste_row.addWidget(clipboard_button)
        paste_row.addStretch(1)
        refresh_button = QPushButton("Actualiser les quantités", self)
        refresh_button.clicked.connect(self._render)
        paste_row.addWidget(refresh_button)
        layout.addLayout(paste_row)

        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["Ressource", "Nécessaire", "Banque", "Inventaire", "Manquant"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, self.table.horizontalHeader().ResizeMode.Stretch
        )
        for index in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(
                index, self.table.horizontalHeader().ResizeMode.ResizeToContents
            )
        layout.addWidget(self.table, 1)

        copy_button = QPushButton("Copier la liste des ressources manquantes", self)
        copy_button.clicked.connect(self._copy_missing)
        layout.addWidget(copy_button)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._render)
        signals = bot.inventory_signals
        for signal in (
            signals.bank_refreshed,
            signals.bank_item_updated,
            signals.bank_item_removed,
            signals.added_object_item,
            signals.added_object_items_batch,
            signals.updated_object_item,
            signals.deleted_object_item_uid,
            signals.clear_inventory,
        ):
            signal.connect(self._schedule_render)
        self.url_imported.connect(self._finish_url_import)
        self._render()

    def _schedule_render(self, *_: object) -> None:
        self._render_timer.start()

    def _item_names(self) -> dict[str, int]:
        if self._gid_by_name is None:
            names = I18N().name_by_id
            self._gid_by_name = {}
            for gid, item in DataReader().item_by_id.items():
                name_id = item.nameId
                name = names.get(int(name_id), "") if name_id is not None else ""
                if not name:
                    continue
                gid = int(gid)
                self._names_by_gid[gid] = str(name)
                self._gid_by_name.setdefault(normalize_item_name(str(name)), gid)
        return self._gid_by_name

    def _item_name(self, gid: int) -> str:
        if gid not in self._names_by_gid:
            item = DataReader().item_by_id.get(gid)
            name_id = item.nameId if item is not None else None
            name = I18N().name_by_id.get(int(name_id), "") if name_id is not None else ""
            self._names_by_gid[gid] = str(name) if name else f"Objet #{gid}"
        return self._names_by_gid[gid]

    def _confirm_replace(self, use_dofusbook: bool) -> bool:
        if self.using_dofusbook == use_dofusbook:
            return True
        if not self.crafts and not self.external_requirements:
            return True
        response = QMessageBox.question(
            self,
            "Remplacer la liste ?",
            "Importer une liste Dofusbook remplace les crafts locaux, et inversement. Continuer ?",
        )
        return response == QMessageBox.StandardButton.Yes

    def _add_craft(self) -> None:
        name = normalize_item_name(self.item_edit.text())
        entries = {
            normalize_item_name(entry.name): entry.recipe.resultId
            for entry in self.catalog.recipe_by_id.values()
        }
        gid = entries.get(name)
        if gid is None:
            QMessageBox.warning(
                self, "Recette introuvable", "Sélectionne une recette dans les suggestions."
            )
            return
        if not self._confirm_replace(False):
            return
        self.using_dofusbook = False
        self.external_requirements.clear()
        self.crafts[gid] = self.crafts.get(gid, 0) + self.amount.value()
        self.item_edit.clear()
        self._update_craft_list()
        self._render()

    def _remove_craft(self) -> None:
        current = self.craft_list.currentItem()
        if current is None:
            return
        gid = int(current.data(Qt.ItemDataRole.UserRole))
        self.crafts.pop(gid, None)
        self._update_craft_list()
        self._render()

    def _update_craft_list(self) -> None:
        self.craft_list.clear()
        for gid, quantity in self.crafts.items():
            entry = self.catalog.recipe_by_id.get(gid)
            if entry is None:
                continue
            from PyQt6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(f"{quantity} × {entry.name}")
            item.setData(Qt.ItemDataRole.UserRole, gid)
            self.craft_list.addItem(item)

    def _import_pasted_text(self) -> None:
        self._apply_imported_text(self.pasted_text.toPlainText())

    def _import_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        text = clipboard.text() if clipboard is not None else ""
        if not text.strip():
            QMessageBox.warning(
                self,
                "Presse-papiers vide",
                "Copie d'abord les ressources visibles de ton atelier dans Chrome "
                "avec Ctrl+C, puis reviens ici.",
            )
            return
        self.pasted_text.setPlainText(text)
        self._apply_imported_text(text)

    def _apply_imported_text(self, text: str) -> None:
        if not text.strip():
            QMessageBox.warning(self, "Atelier vide", "Colle une liste de ressources Dofusbook.")
            return
        if "<html" in text.casefold() or '<div id="app"' in text.casefold():
            QMessageBox.warning(
                self,
                "Code source HTML",
                "Ce fichier contient le programme de Dofusbook, pas tes recettes. "
                "Ouvre l'atelier normalement dans Chrome et copie le contenu "
                "visible, pas « Afficher le code source ».",
            )
            return
        try:
            require_accessible_atelier(text)
            requirements = parse_atelier_text(text, self._item_names())
        except (ValueError, KeyError) as error:
            QMessageBox.warning(self, "Import impossible", str(error))
            return
        if not requirements:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle("Ressources non reconnues")
            dialog.setText(
                "Le lien a été chargé, mais aucune ressource exploitable n'a été reconnue. "
                "Clique sur « Afficher les détails » pour voir le texte réellement "
                "récupéré sur Dofusbook. Tu peux le copier pour diagnostiquer "
                "le format (vérifie les informations personnelles avant de le partager). "
                "Si Dofusbook demande une connexion, colle plutôt la liste visible "
                "depuis ton navigateur."
            )
            excerpt = text.strip()
            dialog.setDetailedText(
                "Texte extrait de la page Dofusbook (limité à 6000 caractères) :\n\n"
                + (excerpt[:6000] if excerpt else "[Page vide ou contenu inaccessible]")
                + f"\n\nLongueur totale : {len(excerpt)} caractères."
            )
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.exec()
            return
        if not self._confirm_replace(True):
            return
        self.using_dofusbook = True
        self.external_requirements = requirements
        self.crafts.clear()
        self._update_craft_list()
        self._render()

    def _import_url(self) -> None:
        if self._importing:
            return
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Lien manquant", "Renseigne l'adresse publique de l'atelier.")
            return
        self._importing = True
        self.url_button.setEnabled(False)
        self.status.setText("Lecture de l'atelier Dofusbook en cours…")

        def worker() -> None:
            try:
                self.url_imported.emit(fetch_public_atelier(url), "")
            except Exception as error:
                self.url_imported.emit("", str(error))

        Thread(target=worker, daemon=True).start()

    def _finish_url_import(self, text: str, error: str) -> None:
        self._importing = False
        self.url_button.setEnabled(True)
        if error:
            QMessageBox.warning(
                self,
                "Atelier inaccessible",
                f"Lecture du lien impossible : {error}\n"
                "Tu peux importer la liste visible depuis Chrome via le "
                "bouton « Importer le presse-papiers ». "
                "Aucun identifiant ni cookie Dofusbook n'est nécessaire.",
            )
            self._render()
            return
        self._apply_imported_text(text)
        self._render()

    def _render(self) -> None:
        state = self.bot.game_state.inventory
        bank_known = state.bank_content_known
        inventory_known = state.inventory_content_known
        requirements = (
            dict(self.external_requirements)
            if self.using_dofusbook
            else craft_requirements(
                (self.catalog.recipe_by_id[gid].recipe, quantity)
                for gid, quantity in self.crafts.items()
                if gid in self.catalog.recipe_by_id
            )
        )
        balance = compare_materials(
            requirements,
            state.bank_objects_by_uid.values(),
            state.objects_by_uid.values(),
        )
        balance.sort(key=lambda row: (-row.missing, self._item_name(row.gid)))
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(balance))
        missing_lines: list[str] = []
        for index, row in enumerate(balance):
            name = self._item_name(row.gid)
            missing = row.missing if bank_known and inventory_known else None
            values = (
                name,
                str(row.required),
                str(row.in_bank) if bank_known else "Non scannée",
                str(row.in_inventory) if inventory_known else "Non scanné",
                str(missing) if missing is not None else "À confirmer",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(index, column, item)
            if missing is not None and missing > 0:
                missing_lines.append(f"{missing} × {name}")
        self._missing_text = "\n".join(missing_lines)
        total = len(balance)
        missing_kinds = sum(row.missing > 0 for row in balance) if bank_known and inventory_known else None
        source = "Atelier Dofusbook importé" if self.using_dofusbook else f"{len(self.crafts)} craft(s)"
        self.summary.setText(
            f"Source : {source} | {total} ressources"
            + (f" | {missing_kinds} ressources manquantes" if missing_kinds is not None else "")
        )
        unknown = []
        if not inventory_known:
            unknown.append("inventaire non reçu")
        if not bank_known:
            unknown.append("banque non scannée : ouvre-la en jeu pour recevoir son contenu")
        self.status.setText(
            "Données de la dernière observation du personnage : "
            + ("; ".join(unknown) if unknown else "banque et inventaire disponibles. "
               "Les quantités se mettent à jour avec les événements reçus.")
        )

    def _copy_missing(self) -> None:
        state = self.bot.game_state.inventory
        if not (state.bank_content_known and state.inventory_content_known):
            QMessageBox.information(
                self,
                "Scan incomplet",
                "Ouvre la banque en jeu et attends la réception de l'inventaire "
                "avant de copier une liste de ressources manquantes fiable.",
            )
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._missing_text or "Aucune ressource manquante.")
