"""Unit tests for read-only craft comparison and Dofusbook list import."""
from types import SimpleNamespace

from src.core.engine.crafts.material_planner import (
    compare_materials,
    craft_requirements,
    stack_quantities,
)
from src.services.dofusbook_atelier import normalize_item_name, parse_atelier_text


def _stack(gid: int, quantity: int):
    return SimpleNamespace(item=SimpleNamespace(gid=gid, quantity=quantity))


def test_combine_stacks_without_modifying_objects():
    first, second = _stack(123, 12), _stack(123, 9)
    assert stack_quantities([first, second]) == {123: 21}
    assert first.item.quantity == 12


def test_full_stuff_craft_requirements_and_missing():
    coiffe = SimpleNamespace(resultId=1, ingredientIds=[123, 456], quantities=[4, 6])
    cape = SimpleNamespace(resultId=2, ingredientIds=[123], quantities=[3])
    needed = craft_requirements([(coiffe, 2), (cape, 1)])
    assert needed == {123: 11, 456: 12}
    result = compare_materials(needed, [_stack(123, 6), _stack(456, 1)], [_stack(123, 3)])
    assert result[0].in_bank == 6
    assert result[0].in_inventory == 3
    assert result[0].missing == 2
    assert result[1].missing == 11


def test_import_dofusbook_list_and_ignore_unknown_names():
    names = {
        normalize_item_name("Peau de Crocabulia"): 11,
        normalize_item_name("Étoffe Mystérieuse"): 22,
    }
    copied = """
    Amakna - 0%
    Image
    Peau de Crocabulia
    0 / 4
    Étoffe Mystérieuse
    2 / 10
    Autre ressource
    0 / 90
    """
    assert parse_atelier_text(copied, names) == {11: 4, 22: 10}


def test_import_multiple_copied_formats():
    names = {normalize_item_name("Peau de Crocabulia"): 11}
    assert parse_atelier_text("Peau de Crocabulia x 8", names) == {11: 8}
    assert parse_atelier_text("8 x Peau de Crocabulia", names) == {11: 8}


def test_unknown_resource_between_known_resource_and_quantity_is_not_attributed():
    names = {normalize_item_name("Étoffe Mystérieuse"): 22}
    copied = """
    Étoffe Mystérieuse
    2 / 10
    Autre ressource
    0 / 90
    """
    assert parse_atelier_text(copied, names) == {22: 10}


def test_orphan_quantity_without_resource_is_ignored():
    names = {normalize_item_name("Peau de Crocabulia"): 11}
    copied = """
    0 / 999
    Peau de Crocabulia
    3 / 8
    0 / 400
    """
    assert parse_atelier_text(copied, names) == {11: 8}


def test_unknown_name_is_not_skipped_to_find_earlier_known_name():
    names = {normalize_item_name("Peau de Crocabulia"): 11}
    copied = """
    Peau de Crocabulia
    Autre ressource
    0 / 77
    """
    assert parse_atelier_text(copied, names) == {}


def test_dofusbook_short_url_is_allowed():
    from src.services.dofusbook_atelier import _validate_url

    _validate_url("https://d-bk.net/fr/dw/2kN6")
    _validate_url("https://www.d-bk.net/fr/dw/2kN6")
    _validate_url("https://www.dofusbook.net/desktop/fr/")


def test_dofusbook_short_url_rejects_impostors():
    import pytest

    from src.services.dofusbook_atelier import _validate_url

    for url in (
        "http://d-bk.net/fr/dw/2kN6",
        "https://d-bk.net.attacker.example/fr/dw/2kN6",
        "https://d-bk.net@attacker.example/fr/dw/2kN6",
        "https://evil.example/fr/dw/2kN6",
        "https://user:password@d-bk.net/fr/dw/2kN6",
    ):
        with pytest.raises(ValueError):
            _validate_url(url)


def test_javascript_shell_without_ingredients_needs_browser():
    from src.services.dofusbook_atelier import _has_visible_quantities

    assert not _has_visible_quantities("Dofusbook Mes crafts Atelier")
    assert _has_visible_quantities("Peau de Crocabulia\n0 / 4")


def test_detect_cloudflare_blocked_page():
    import pytest

    from src.services.dofusbook_atelier import is_access_blocked, require_accessible_atelier

    block = (
        "Sorry, you have been blocked\n"
        "You are unable to access dofusbook.net\n"
        "Cloudflare Ray ID: a5e26481eb7d6ed9"
    )
    assert is_access_blocked(block)
    with pytest.raises(ValueError, match="Cloudflare"):
        require_accessible_atelier(block)
    assert not is_access_blocked("Peau de Crocabulia\n0 / 4")


def test_import_copied_browser_row_with_quantities_on_same_line():
    names = {normalize_item_name("Peau de Crocabulia"): 11}
    copied = "Peau de Crocabulia\t0 / 4\nPeau inconnue\t0 / 100"
    assert parse_atelier_text(copied, names) == {11: 4}


def test_unknown_inline_item_does_not_change_known_item_amount():
    names = {normalize_item_name("Étoffe Mystérieuse"): 22}
    copied = "Étoffe Mystérieuse\t3 / 10\nAutre ressource\t0 / 90"
    assert parse_atelier_text(copied, names) == {22: 10}
