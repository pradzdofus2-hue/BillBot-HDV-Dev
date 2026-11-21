#!/usr/bin/env python3
r"""BillBot officiel 6.0_3.7.13.17 + correctifs HDV: charger un maximum de ressources en banque.

Cible le module de vente et ajoute un mode exhaustif facultatif au chargeur banque.
Les autres comportements de chargement ne changent pas.
Ne s'applique qu'après INSTALLER-BILLBOT-OFFICIEL-HDV.py,
CORRIGER-BILLBOT-BANQUE-HDV.py et CORRIGER-BILLBOT-QUOTAS-HDV.py.

Utilisation (PowerShell, à la racine BillBot-Officiel-HDV):
  uv run python .\OPTIMISER-BILLBOT-HDV-PODS.py --check
  uv run python .\OPTIMISER-BILLBOT-HDV-PODS.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT_COMMIT = '52fa2a9d4575f5ee954e7e23c027d5175f9bf308'
VERSION = '6.0_3.7.13.17'
TARGET = Path('src/core/behaviors/sale_hotel/sale_hotel_sell_behavior.py')
LOADER_TARGET = Path('src/core/behaviors/storage/loads/load_from_bank_behavior.py')
MARK = '# HDV_BULK_PODS_V4: fill available carry capacity before leaving bank'
REQUIRED_MARKS = (
    '# HDV_BANK_V2_PATCH: fresh bank snapshot + verified inventory before HDV',
    '# HDV_BANK_QUOTA_V3: nonzero bank-stock withdrawals, no shared-listing quota',
)


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: attendu 1 occurrence, trouvé {count}; aucun changement.')
    return text.replace(old, new, 1)


def replace_method(source: str, name: str, replacement: str) -> str:
    found = re.search(rf'(?m)^    def {re.escape(name)}\(', source)
    if not found:
        raise RuntimeError(f'Méthode {name} introuvable; aucun changement.')
    end_match = re.search(r'(?m)^    (?:async )?def [a-zA-Z_]\w*\(', source[found.end():])
    end = found.end() + end_match.start() if end_match else len(source)
    original = source[found.start():end]
    if not original.startswith(f'    def {name}('):
        raise RuntimeError(f'Méthode {name} : extraction invalide.')
    return source[:found.start()] + replacement + '\n\n' + source[end:]


BULK_SELECT_METHOD = '''    def sell_next_category(self) -> None:
        if not self.categories:
            return self.finish()
        self._curr_category = self.categories.pop()

        # La banque vient d'être synchronisée par on_sale_bank_opened.
        # Ne pas utiliser get_bank_objects_by_gid() ici : son agrégation modifie
        # potentiellement la quantité d'une pile de la banque en mémoire.
        inventory = self.game_state.inventory
        free_pods = max(0, inventory.weight_max - inventory.inventory_weight)
        self.logger.info(
            "HDV BULK : capacité sac=%s pods, occupé=%s, libres=%s, piles banque=%s",
            inventory.weight_max, inventory.inventory_weight, free_pods,
            len(inventory.bank_objects_by_uid),
        )
        if free_pods <= 0:
            self.logger.warning("HDV BULK : aucun pod libre; vider le sac avant la vente")
            return self.finish("HDV_NO_FREE_PODS")

        reader = DataReader()
        avg_prices = GameDataController().get_avg_price_by_gid(self.game_state.player.server_id)
        stocks: dict[int, int] = {}
        for stored in inventory.bank_objects_by_uid.values():
            if stored.item.quantity > 0:
                gid = stored.item.gid
                stocks[gid] = stocks.get(gid, 0) + stored.item.quantity

        # Sélectionner les ressources vendables, même quand leur petite quantité
        # était écartée par le filtre « rentable » de l'ancien bot. L'HDV refusera
        # toujours de les lister si le prix EXACT de leur lot est inconnu/incorrect.
        candidates: list[tuple[int, int, int, float]] = []
        ignored = {"not_resource": 0, "not_available": 0, "unknown": 0}
        for gid, stock in stocks.items():
            data = reader.item_by_id.get(gid)
            if data is None or not data.typeId:
                ignored["unknown"] += 1
                continue
            category = reader.item_type_by_id.get(data.typeId)
            if category is None or category.categoryId != CategoryItemEnum.RESOURCES:
                ignored["not_resource"] += 1
                continue
            if not (self.game_state.player.is_sub or (data.level or 0) <= 60):
                ignored["not_available"] += 1
                continue
            weight = max(1, int(data.realWeight or 1))
            estimated_unit_price = max(1.0, float(avg_prices.get(gid, 0) or 0))
            candidates.append((gid, stock, weight, estimated_unit_price))

        # Privilégier la valeur transportée par pod. Une pile 1 unité ne doit pas
        # empêcher le chargement d'autres ressources dans le même déplacement.
        candidates.sort(
            key=lambda c: (
                c[3] / c[2],
                min(c[1], free_pods // c[2]) * c[3],
                c[1],
            ),
            reverse=True,
        )
        self._load_items_infos = []
        self._item_ids_to_sell = []
        self._sale_inventory_before_bank = {}
        remaining_pods = free_pods
        planned_units = 0
        for gid, stock, weight, avg_price in candidates:
            qty = min(stock, MAX_QUANTITY_ON_SELL, remaining_pods // weight)
            if qty <= 0:
                continue
            self._load_items_infos.append(
                LoadItemInfo(
                    item_gid=gid,
                    remaining_quantity=qty,
                    tab=get_tab_by_gid().get(gid, 0),
                )
            )
            self._item_ids_to_sell.append(gid)
            self._sale_inventory_before_bank[gid] = sum(
                stored.item.quantity
                for stored in inventory.objects_by_uid.values()
                if stored.item.gid == gid
            )
            planned_units += qty
            remaining_pods -= qty * weight
            self.logger.info(
                "HDV BULK : gid=%s banque=%s, poids=%s, estimation unitaire=%s,"
                " retrait prévu=%s, pods restants=%s",
                gid, stock, weight, round(avg_price, 2), qty, remaining_pods,
            )
            if remaining_pods <= 0:
                break

        self.logger.info(
            "HDV BULK : %s types, %s unités prévues, %s/%s pods utilisés,"
            " %s ressources banque (%s ignorées)",
            len(self._load_items_infos), planned_units,
            free_pods - remaining_pods, free_pods,
            len(stocks), ignored,
        )
        if not self._load_items_infos:
            self.logger.warning(
                "HDV BULK : aucune ressource transportable. Vérifier les pods, "
                "l'abonnement, les types d'objet et le contenu de la banque."
            )
            return self.finish("HDV_NOTHING_TO_LOAD")
        self.load_items()
'''


def patch(source: str) -> str:
    if MARK in source:
        return source
    for marker in REQUIRED_MARKS:
        if marker not in source:
            raise RuntimeError(f'Patch préalable manquant : {marker}')
    for marker in (
        'class SaleHotelSellBehavior(RecoverableBehavior):',
        'def on_sale_bank_opened(',
        'def on_loaded_behavior_finished(',
        'def create_all_prices(',
        'def create_price(',
        'self.enter_sale_hotel_sell_behavior.start(',
        'def load_items(',
    ):
        if marker not in source:
            raise RuntimeError(f'Fichier vente HDV inattendu : marqueur absent {marker}')

    source = replace_one(
        source,
        'from src.core.config import MIN_KAMAS_TO_GO_SALE_HOTEL\n',
        'from src.core.config import MAX_QUANTITY_ON_SELL, MIN_KAMAS_TO_GO_SALE_HOTEL\n',
        'activer le plafond global de chargement par ressource',
    )
    source = replace_one(
        source,
        '    _sale_bank_visits: int = field(init=False, default=0)\n',
        '    _sale_bank_visits: int = field(init=False, default=0)\n'
        '    _sale_inventory_before_bank: dict[int, int] = field(init=False, default_factory=dict)\n',
        'retenir le stock de départ pour confirmer le retrait',
    )
    source = replace_method(source, 'sell_next_category', BULK_SELECT_METHOD)

    # Ne pas lancer une opération de vidage automatique après le calcul des pods :
    # le plan porte sur la capacité du sac mesurée au moment de l'ouverture banque.
    source = replace_one(
        source,
        '            load_items_infos=self._load_items_infos,\n        )\n\n    def on_loaded_behavior_finished(',
        '            load_items_infos=self._load_items_infos,\n'
        '            unload_first=False,\n'
        '            exhaustive=True,\n        )\n\n    def on_loaded_behavior_finished(',
        'éviter de changer le sac après la planification des pods',
    )

    # Si une partie de la commande n'a pas pu être chargée, ne pas déclencher
    # d'autres frais d'ouverture bancaire automatiquement avec une liste partielle.
    source = replace_one(
        source,
        '                return self.load_items()\n\n            next_item =',
        '                self.logger.warning(\n'
        '                    "HDV BULK : des retraits sont restés en attente après le voyage; "\n'
        '                    "fin du passage pour éviter de nouveaux frais de banque"\n'
        '                )\n'
        '                return self.finish()\n\n            next_item =',
        'éviter les trajets banque successifs pour des reliquats',
    )

    # Le chargeur retourne parfois un succès sans changement d'inventaire :
    # ne pas accepter des ressources préexistantes comme preuve de retrait.
    expected = '        self.logger.info("HDV vente : inventaire vérifié avant trajet HDV : %s", stock)\n'
    confirmation = '''        transferred = sum(
            max(0, stock.get(gid, 0) - self._sale_inventory_before_bank.get(gid, 0))
            for gid in self._item_ids_to_sell
        )
        if transferred <= 0:
            self.logger.error(
                "HDV BULK : aucun objet réellement transféré depuis la banque, "
                "annulation du trajet HDV. Pods=%s/%s, restants=%s",
                self.game_state.inventory.inventory_weight,
                self.game_state.inventory.weight_max,
                load_items_infos,
            )
            return self.finish("HDV_NO_CONFIRMED_WITHDRAWAL")
        self.logger.info(
            "HDV BULK : retrait confirmé de %s unités ; inventaire avant HDV : %s",
            transferred, stock,
        )
'''
    source = replace_one(source, expected, confirmation, 'confirmer les ressources transférées')

    # Ne pas ignorer les ressources de petite quantité une fois sélectionnées,
    # puisque le prix exact du lot reste vérifié avant toute mise en vente.
    original_interest = '''            if is_interesting_item_to_sell(
                next_item,
                GameDataController().get_avg_price_by_gid(self.game_state.player.server_id),
            ):
                break
'''
    source = replace_one(
        source, original_interest,
        '''            if next_item.quantity > 0:
                break
''',
        'ne plus ignorer une ressource correctement retirée',
    )
    source = replace_one(
        source,
        '        if not is_interesting_item_to_sell(item, avg_price_by_gid, remaining):\n',
        '        if remaining <= 0:\n',
        'ne pas écarter les petites piles avant la vérification du prix réel du lot',
    )
    # Mettre le marqueur après les modifications validées.
    source = source.replace(REQUIRED_MARKS[-1], REQUIRED_MARKS[-1] + '\n' + MARK, 1)
    compile(source, str(TARGET), 'exec')
    return source


def patch_loader(source: str) -> str:
    """Mode HDV uniquement: NE PAS abandonner une demande dès que son reliquat < 100.

    Par défaut, les autres modules conservent la logique officielle.
    """
    marker = '# HDV_BULK_BANK_EXHAUSTIVE_V4'
    if marker in source:
        return source
    source = replace_one(
        source,
        '    _pending_load_items: list[PendingLoadItem] = field(init=False, default_factory=lambda: [])\n',
        '    _pending_load_items: list[PendingLoadItem] = field(init=False, default_factory=lambda: [])\n'
        '    _exhaustive_loading: bool = field(init=False, default=False)  # ' + marker + '\n',
        'ajouter un mode de retrait exhaustif isolé',
    )
    source = replace_one(
        source,
        '    def run(self, load_items_infos: list[LoadItemInfo], unload_first: bool = True) -> None:\n'
        '        self.init_recovery_listeners()\n',
        '    def run(\n'
        '        self, load_items_infos: list[LoadItemInfo], unload_first: bool = True, exhaustive: bool = False\n'
        '    ) -> None:\n'
        '        self._exhaustive_loading = exhaustive\n'
        '        self.init_recovery_listeners()\n',
        'exposer un retrait exhaustif facultatif aux comportements HDV',
    )
    source = replace_one(
        source,
        '        if current_load.remaining_quantity < 100:\n'
        '            self._pending_load_items.pop(0)\n',
        '        if current_load.remaining_quantity <= 0 or (\n'
        '            not self._exhaustive_loading and current_load.remaining_quantity < 100\n'
        '        ):\n'
        '            self._pending_load_items.pop(0)\n',
        'continuer les retraits HDV jusqu’à la quantité voulue, même par piles de 1',
    )
    compile(source, str(LOADER_TARGET), 'exec')
    return source


def check_planner() -> None:
    """Validation arithmétique de la priorité pods sur des stocks synthétiques."""
    def plan(stocks: list[tuple[int, int]], capacity: int) -> list[int]:
        left = capacity
        result: list[int] = []
        for qty, weight in stocks:
            taken = min(qty, 10_000, left // weight)
            result.append(taken)
            left -= taken * weight
        return result
    assert plan([(1, 1), (50, 1), (200, 2)], 100) == [1, 50, 24]
    assert plan([(5000, 2), (300, 1)], 1200) == [600, 0]
    assert plan([(1, 1), (250, 1)], 100) == [1, 99]
    assert plan([(10000, 1)], 750) == [750]


def main() -> int:
    parser = argparse.ArgumentParser(description='HDV banque : charger autant de ressources que les pods permettent')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true', help='Vérifier sans écrire')
    modes.add_argument('--apply', action='store_true', help='Sauvegarder puis installer')
    opts = parser.parse_args()
    try:
        check_planner()
        root = Path(__file__).resolve().parent
        if not (root / '.git').is_dir():
            raise RuntimeError('Placer le script à la racine de BillBot-Officiel-HDV.')
        head = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=root, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if head != ROOT_COMMIT:
            raise RuntimeError(f'Base Git non reconnue : {head[:12]}; attendu {ROOT_COMMIT[:12]}.')
        if (root / 'VERSION').read_text(encoding='utf-8').strip() != VERSION:
            raise RuntimeError('Ce correctif nécessite BillBot 6.0_3.7.13.17.')
        target = root / TARGET
        original_bytes = target.read_bytes()
        encoding = 'utf-8-sig' if original_bytes.startswith(b'\xef\xbb\xbf') else 'utf-8'
        original = original_bytes.decode(encoding).replace('\r\n', '\n')
        result = patch(original)
        loader = root / LOADER_TARGET
        loader_original_bytes = loader.read_bytes()
        loader_encoding = 'utf-8-sig' if loader_original_bytes.startswith(b'\xef\xbb\xbf') else 'utf-8'
        loader_original = loader_original_bytes.decode(loader_encoding).replace('\r\n', '\n')
        loader_result = patch_loader(loader_original)
        if result == original and loader_result == loader_original:
            print('[OK] Optimisation pods et retrait exhaustif déjà présents ; aucune modification.')
            return 0
        newline = '\r\n' if b'\r\n' in original_bytes else '\n'
        result_bytes = result.replace('\n', newline).encode(encoding)
        loader_newline = '\r\n' if b'\r\n' in loader_original_bytes else '\n'
        loader_result_bytes = loader_result.replace('\n', loader_newline).encode(loader_encoding)
        print('[OK] Base officielle et correctifs HDV reconnus.')
        print('[OK] Planification de plusieurs ressources selon les pods, avec trace des quantités.')
        print('[OK] Retrait des piles de 1 jusqu’à la quantité demandée (HDV uniquement).')
        print('[OK] Retrait réel vérifié avant tout départ à l’HDV.')
        print('[OK] Fichiers concernés :', TARGET.as_posix(), 'et', LOADER_TARGET.as_posix())
        if opts.check:
            print('[OK] Aucun fichier modifié (--check).')
            return 0
        backup = Path(tempfile.gettempdir()) / (
            'BillBot-HDV-AvantBulkPods-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip'
        )
        with zipfile.ZipFile(backup, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(TARGET.as_posix(), original_bytes)
            zf.writestr(LOADER_TARGET.as_posix(), loader_original_bytes)
        # Toutes les vérifications sont terminées avant la première écriture.
        # Si l'écriture du second fichier échoue, restaurer le premier.
        changed = []
        try:
            for destination, payload, before in (
                (target, result_bytes, original_bytes),
                (loader, loader_result_bytes, loader_original_bytes),
            ):
                if payload == before:
                    continue
                pending = None
                try:
                    with tempfile.NamedTemporaryFile(
                        'wb', prefix='.bulk-pods-', suffix='.tmp', dir=destination.parent, delete=False
                    ) as stream:
                        pending = Path(stream.name)
                        stream.write(payload)
                    os.replace(pending, destination)
                    pending = None
                    changed.append((destination, before))
                finally:
                    if pending is not None:
                        pending.unlink(missing_ok=True)
        except Exception:
            for destination, previous in reversed(changed):
                destination.write_bytes(previous)
            raise
        print('[OK] Optimisation installée ; sauvegarde :', backup)
        print('[INFO] Lancer : uv run python __main__.py')
        return 0
    except (OSError, RuntimeError, SyntaxError, UnicodeError, subprocess.CalledProcessError) as error:
        print('[ECHEC]', error)
        print('[AUCUNE MODIFICATION] Vérification arrêtée sans écriture si l’erreur est avant la sauvegarde.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
