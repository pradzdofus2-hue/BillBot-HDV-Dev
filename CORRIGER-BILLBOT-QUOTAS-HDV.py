#!/usr/bin/env python3
"""BillBot-Officiel-HDV : réparer le calcul des quantités à retirer en banque.

Compatible avec INSTALLER-BILLBOT-OFFICIEL-HDV.py + CORRIGER-BILLBOT-BANQUE-HDV.py.
N'altère QUE src/core/behaviors/sale_hotel/sale_hotel_sell_behavior.py.

Lancer depuis le dossier BillBot-Officiel-HDV :
  uv run python CORRIGER-BILLBOT-QUOTAS-HDV.py --check
  uv run python CORRIGER-BILLBOT-QUOTAS-HDV.py --apply
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

TARGET = Path('src/core/behaviors/sale_hotel/sale_hotel_sell_behavior.py')
MARK = '# HDV_BANK_QUOTA_V3: nonzero bank-stock withdrawals, no shared-listing quota'
PREVIOUS_MARK = '# HDV_BANK_V2_PATCH: fresh bank snapshot + verified inventory before HDV'
EXPECTED_COMMIT = '52fa2a9d4575f5ee954e7e23c027d5175f9bf308'
EXPECTED_VERSION = '6.0_3.7.13.17'


def change_once(source: str, before: str, after: str, label: str) -> str:
    n = source.count(before)
    if n != 1:
        raise RuntimeError(f'{label}: attendu exactement 1 fragment, trouvé {n}. Rien modifié.')
    return source.replace(before, after, 1)


def plan_with_bank_stock(stock: int, max_quantity_sell: int) -> int:
    """One conservative sale pass, independent of other characters' HDV listings.

    A protector drop with max_quantity_sell=1 must produce 1, never floor(1/4)=0.
    """
    if stock <= 0 or max_quantity_sell <= 0:
        return 0
    return min(stock, max(1, max_quantity_sell // 4))


def patch(source: str) -> str:
    if MARK in source:
        return source
    for required in (
        PREVIOUS_MARK,
        'class SaleHotelSellBehavior(RecoverableBehavior):',
        'self.enter_sale_hotel_sell_behavior.start(',
        'HDV_BANK_LOAD_EMPTY',
        'self._item_ids_to_sell = get_item_gids_to_sell(',
        'self.game_state.inventory.get_bank_objects_by_gid(),',
        'if remaining_qty <= 0:',
    ):
        if required not in source:
            raise RuntimeError(f'Version locale différente ; marqueur absent : {required!r}.')

    # Before the original helper aggregates objects by GID (and can mutate one stack),
    # capture the actual quantities by bank-UID. This also supports multiple stacks per GID.
    source = change_once(
        source,
        '        self._item_ids_to_sell = get_item_gids_to_sell(\n',
        '''        bank_quantity_by_gid: dict[int, int] = {}
        for stored in self.game_state.inventory.bank_objects_by_uid.values():
            gid = stored.item.gid
            bank_quantity_by_gid[gid] = (
                bank_quantity_by_gid.get(gid, 0) + max(0, stored.item.quantity)
            )
        self.logger.info(
            "HDV vente : banque synchronisée, %s piles et %s ressources distinctes en stock",
            len(self.game_state.inventory.bank_objects_by_uid),
            len(bank_quantity_by_gid),
        )

        self._item_ids_to_sell = get_item_gids_to_sell(
''',
        'capture du vrai stock avant tri',
    )

    source = change_once(
        source,
        '''            remaining_qty = min(
                max(max_quantity_sell - item_sell_quantity_by_gid.get(item_gid, 0), 0),
                math.floor(max_quantity_sell / 4),
            )
''',
        '''            # Le cumul des annonces était calculé sur TOUS les personnages du serveur.
            # Il annulait le retrait même quand le personnage possède du stock en banque.
            # Limiter uniquement la quantité prélevée par passage et au stock réel.
            bank_stock = bank_quantity_by_gid.get(item_gid, 0)
            per_pass_limit = max(1, max_quantity_sell // 4)
            remaining_qty = min(bank_stock, per_pass_limit)
            self.logger.info(
                "HDV vente : gid=%s stock=%s, cumul historique annonces=%s (non bloquant), "
                "limite par passage=%s => retrait=%s",
                item_gid,
                bank_stock,
                item_sell_quantity_by_gid.get(item_gid, 0),
                per_pass_limit,
                remaining_qty,
            )
''',
        'ne plus bloquer les retraits avec un quota global/arrondi à zéro',
    )

    source = change_once(
        source,
        '            self.logger.warning("HDV vente : aucune ressource à retirer (stock/quotas), arrêt")\n',
        '''            self.logger.warning(
                "HDV vente : aucun retrait possible. Stock banque=%s, candidats=%s, "
                "sous quota par passage=%s. Vérifier le type des objets et le stock.",
                len(bank_quantity_by_gid),
                self._item_ids_to_sell,
                len(self._load_items_infos),
            )
''',
        'journal plus explicite si le stockage est réellement vide',
    )
    source = source.replace(PREVIOUS_MARK, PREVIOUS_MARK + '\n' + MARK, 1)
    compile(source, str(TARGET), 'exec')
    return source


def check_planner() -> None:
    assert plan_with_bank_stock(50, 10_000) == 50
    assert plan_with_bank_stock(5_000, 10_000) == 2_500
    assert plan_with_bank_stock(1, 1) == 1
    assert plan_with_bank_stock(0, 10_000) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Fixe le retrait HDV banque sans toucher aux autres modules')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true', help='Vérifier les fichiers sans les modifier')
    modes.add_argument('--apply', action='store_true', help='Sauvegarder et appliquer la correction')
    opts = parser.parse_args()

    try:
        check_planner()
        root = Path(__file__).resolve().parent
        if not (root / '.git').is_dir():
            raise RuntimeError('Placer ce script à la racine du clone BillBot-Officiel-HDV.')
        sha = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        if sha != EXPECTED_COMMIT:
            raise RuntimeError(f'Base Git différente ({sha[:12]}); attendre {EXPECTED_COMMIT[:12]}.')
        if (root / 'VERSION').read_text(encoding='utf-8').strip() != EXPECTED_VERSION:
            raise RuntimeError('Version BillBot différente : ce patch vise 6.0_3.7.13.17.')
        target = root / TARGET
        raw = target.read_bytes()
        encoding = 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'
        original = raw.decode(encoding)
        normalized = original.replace('\r\n', '\n')
        updated = patch(normalized)
        if updated == normalized:
            print('[OK] Correction du retrait déjà présente ; aucune écriture nécessaire.')
            return 0
        newline = '\r\n' if b'\r\n' in raw else '\n'
        updated_bytes = updated.replace('\n', newline).encode(encoding)
        print('[OK] Base officielle + modules HDV et correctif banque reconnus.')
        print('[OK] Retrait planifié d’après les quantités en banque, sans quota historique intercomptes.')
        print('[OK] Exemple : 1 ressource avec plafond 1 -> 1 retirée ; 5000 avec plafond 10000 -> 2500.')
        print('[OK] Seul fichier modifié :', TARGET.as_posix())
        if opts.check:
            print('[OK] Contrôle réussi : aucun fichier modifié.')
            return 0

        backup = Path(tempfile.gettempdir()) / (
            'BillBot-HDV-AvantCorrectionQuotas-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip'
        )
        with zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(TARGET.as_posix(), raw)
        # Write a temporary file next to target, then atomically replace it.
        with tempfile.NamedTemporaryFile('wb', dir=target.parent, delete=False, prefix='.hdv-', suffix='.tmp') as f:
            temporary = Path(f.name)
            f.write(updated_bytes)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        print('[OK] Correctif appliqué. Sauvegarde :', backup)
        print('[OK] Démarrer : uv run python __main__.py')
        return 0
    except (OSError, RuntimeError, SyntaxError, UnicodeError, subprocess.CalledProcessError) as exc:
        print('[ECHEC]', exc)
        print('[AUCUN CHANGEMENT] Aucun fichier BillBot modifié par cet essai.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
