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
