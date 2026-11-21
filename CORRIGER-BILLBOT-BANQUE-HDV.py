#!/usr/bin/env python3
"""Correctif ciblé pour BillBot OFFICIEL + INSTALLER-BILLBOT-OFFICIEL-HDV.

Le bot doit ouvrir la banque et lire son stock à jour AVANT de choisir les
ressources à vendre. Il ne peut ensuite aller à l'HDV que si des ressources
sélectionnées sont réellement dans son inventaire.

Exécution : uv run python CORRIGER-BILLBOT-BANQUE-HDV.py --check
            uv run python CORRIGER-BILLBOT-BANQUE-HDV.py --apply
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ORIGINAL_HEAD = '52fa2a9d4575f5ee954e7e23c027d5175f9bf308'
VERSION = '6.0_3.7.13.17'
SELLER = Path('src/core/behaviors/sale_hotel/sale_hotel_sell_behavior.py')
UPDATER = Path('src/core/behaviors/sale_hotel/sale_hotel_update_prices_behavior.py')
PRICE_GUARD = Path('src/core/behaviors/sale_hotel/sale_hotel_price_guard.py')
MARK = '# HDV_BANK_V2_PATCH: fresh bank snapshot + verified inventory before HDV'


def replace_once(text: str, before: str, after: str, label: str) -> str:
    num = text.count(before)
    if num != 1:
        raise RuntimeError(f'{label}: attendu 1 occurrence, trouve {num}. Aucune modification.')
    return text.replace(before, after, 1)


def replace_method(source: str, name: str, transform):
    pattern = rf'(?m)^    def {re.escape(name)}\('
    match = re.search(pattern, source)
    if not match:
        raise RuntimeError(f'Fonction {name} introuvable. Aucune modification.')
    nxt = re.search(r'(?m)^    (?:async )?def [a-zA-Z_]\w*\(', source[match.end():])
    end = match.end() + nxt.start() if nxt else len(source)
    original = source[match.start():end]
    updated = transform(original)
    return source[:match.start()] + updated + source[end:]


def correct_seller(source: str) -> str:
    if MARK in source:
        return source
    checks = (
        'class SaleHotelSellBehavior(RecoverableBehavior)',
        '_sale_bank_visits',
        'get_verified_lot_price',
        'self.categories = {CategoryItemEnum.RESOURCES}',
        'self.load_from_bank_behavior.start(',
        'self.enter_sale_hotel_sell_behavior.start(',
    )
    for marker in checks:
        if marker not in source:
            raise RuntimeError(f'Le module vente ne correspond pas au correctif HDV officiel (manque {marker!r}).')

    def start_selling(method: str) -> str:
        method = replace_once(
            method,
            '        self.sell_next_category()\n',
            '''        # Toujours rafraîchir la banque AVANT de calculer les ressources vendables.
        # L'ancien code choisissait sur un inventaire de banque potentiellement périmé.
        self.logger.info("HDV vente : ouverture banque et lecture du stock actuel")
        self.load_from_bank_behavior.enter_bank_behavior.start(
            callback=self.on_sale_bank_opened,
            parent=self,
        )
''',
            'Ouvrir la banque avant de planifier la vente',
        )
        return method + '''    def on_sale_bank_opened(self, error_code: str | None) -> None:
        """La trame StorageInventoryContentEvent est traitée par BankChestFrame avant ce rappel."""
        if error_code is not None:
            self.logger.warning("HDV vente : impossible de lire la banque : %s", error_code)
            return self.finish(error_code)
        if not self.game_state.inventory.bank_content_known:
            self.logger.error("HDV vente : banque ouverte, mais aucun contenu de coffre synchronisé")
            return self.finish("HDV_BANK_CONTENT_NOT_SYNCED")
        self.logger.info(
            "HDV vente : stock banque actualisé (%s objets), sélection en cours",
            len(self.game_state.inventory.bank_objects_by_uid),
        )
        self.sell_next_category()

'''

    source = replace_once(
        source, 'class SaleHotelSellBehavior(RecoverableBehavior):',
        f'{MARK}\nclass SaleHotelSellBehavior(RecoverableBehavior):', 'marque de version'
    )
    source = replace_method(source, 'start_selling', start_selling)

    def select_items(method: str) -> str:
        method = replace_once(
            method,
            '            self.game_state.guild_chest.can_access_guild_chest,\n',
            '            False,  # vente HDV depuis la banque uniquement\n',
            'sélectionner le stock de banque, pas le coffre de guilde',
        )
        method = replace_once(
            method,
            '            load_item_info = LoadItemInfo(\n',
            '''            if remaining_qty <= 0:
                self.logger.debug("HDV vente : gid %s ignoré, quota déjà atteint", item_gid)
                continue
            load_item_info = LoadItemInfo(
''',
            'ignorer les demandes de retrait à 0 unité',
        )
        method = replace_once(
            method,
            '        self.load_items()\n',
            '''        # Ne pas envoyer la banque/HDV des requêtes vides : il n'y aurait aucun retrait.
        self._item_ids_to_sell = [request.item_gid for request in self._load_items_infos]
        if not self._load_items_infos:
            self.logger.warning("HDV vente : aucune ressource à retirer (stock/quotas), arrêt")
            return self.finish()
        self.load_items()
''',
            'ne pas lancer le retrait avec une liste vide',
        )
        return method
    source = replace_method(source, 'sell_next_category', select_items)

    def bank_only(method: str) -> str:
        m = re.search(r'(?m)^        if self\.game_state\.guild_chest\.can_access_guild_chest:\n', method)
        if not m:
            raise RuntimeError('La sélection banque/guilde a changé; arrêt de sécurité.')
        method = method[:m.start()] + '''        # Cette action travaille exclusivement sur la banque.
        self.load_from_bank_behavior.start(
            callback=self.on_loaded_behavior_finished,
            parent=self,
            load_items_infos=self._load_items_infos,
        )

'''
        return method
    source = replace_method(source, 'load_items', bank_only)

    def verify_inventory(method: str) -> str:
        needle = '''        self._load_items_infos = load_items_infos
        self.enter_sale_hotel_sell_behavior.start(
'''
        after = '''        self._load_items_infos = load_items_infos
        # Le chargeur pouvait signaler une fin normale sans avoir retiré un seul objet
        # (stock périmé, quota 0, inventaire plein, objet absent). Vérifier le sac.
        stock = {
            gid: sum(
                obj.item.quantity
                for obj in self.game_state.inventory.objects_by_uid.values()
                if obj.item.gid == gid and obj.item.quantity > 0
            )
            for gid in self._item_ids_to_sell
        }
        available = [gid for gid, qty in stock.items() if qty > 0]
        if not available:
            inventory = self.game_state.inventory
            self.logger.error(
                "HDV vente : retrait terminé SANS ressource dans le sac ; "
                "gid demandés=%s, banque connue=%s, pods=%s/%s, restants=%s. "
                "Trajet HDV annulé.",
                self._item_ids_to_sell,
                inventory.bank_content_known,
                inventory.inventory_weight,
                inventory.weight_max,
                load_items_infos,
            )
            return self.finish("HDV_BANK_LOAD_EMPTY")
        self.logger.info("HDV vente : inventaire vérifié avant trajet HDV : %s", stock)
        self.enter_sale_hotel_sell_behavior.start(
'''
        return replace_once(method, needle, after, 'vérifier le vrai inventaire après retrait')
    source = replace_method(source, 'on_loaded_behavior_finished', verify_inventory)

    def safe_sell_inventory(method: str) -> str:
        needle = '        self.create_all_prices()\n'
        after = '''        if not self._item_to_sells_in_inventory:
            self.logger.error("HDV vente : ressources absentes du sac à l'arrivée, arrêt")
            return self.finish("HDV_INVENTORY_EMPTY")
        self.create_all_prices()
'''
        return replace_once(method, needle, after, 'vérifier les objets à l’arrivée à l’HDV')
    source = replace_method(source, 'sell_inventory', safe_sell_inventory)
    compile(source, str(SELLER), 'exec')
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    try:
        if not (root / '.git').exists():
            raise RuntimeError('Ce script doit être dans BillBot-Officiel-HDV (clone Git officiel).')
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        if head != ORIGINAL_HEAD:
            raise RuntimeError(f'HEAD inattendu {head[:12]}; attendu {ORIGINAL_HEAD[:12]}.')
        if (root / 'VERSION').read_text(encoding='utf-8').strip() != VERSION:
            raise RuntimeError('Version attendue : 6.0_3.7.13.17.')
        if not (root / UPDATER).is_file() or not (root / PRICE_GUARD).is_file():
            raise RuntimeError('Installer d’abord INSTALLER-BILLBOT-OFFICIEL-HDV.py --apply.')
        target = root / SELLER
        before = target.read_bytes()
        newline = '\r\n' if b'\r\n' in before else '\n'
        normalized = before.decode('utf-8-sig').replace('\r\n', '\n')
        changed = correct_seller(normalized)
        if changed == normalized:
            print('[OK] Correctif banque déjà présent. Aucun changement nécessaire.')
            return 0
        payload = changed.replace('\n', newline).encode('utf-8')
        compile(changed, str(SELLER), 'exec')
        print('[OK] Compatible : BillBot officiel + modules HDV séparés.')
        print('[OK] Nouvelle séquence : banque fraîche -> quantités > 0 -> retrait -> vérification sac -> HDV.')
        print('[OK] Seul fichier concerné :', SELLER)
        if args.check:
            print('[OK] Mode --check : aucun fichier modifié.')
            return 0
        out = Path(tempfile.gettempdir()) / (
            'BillBot-HDV-Seller-AvantBanque-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip'
        )
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(str(SELLER).replace('\\', '/'), before)
        try:
            target.write_bytes(payload)
        except Exception:
            target.write_bytes(before)
            raise
        print('[OK] Correctif banque appliqué. Sauvegarde :', out)
        print('[OK] Lancement : uv run python __main__.py')
        return 0
    except (OSError, subprocess.CalledProcessError, RuntimeError, SyntaxError, UnicodeError) as exc:
        print('[ECHEC]', exc)
        print('[SECURITE] Aucune modification effectuée par ce script.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
