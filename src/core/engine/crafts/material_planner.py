"""Read-only craft ingredient planning from the bot's existing item snapshots."""
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class MaterialBalance:
    gid: int
    required: int
    in_bank: int
    in_inventory: int

    @property
    def owned(self) -> int:
        return self.in_bank + self.in_inventory

    @property
    def missing(self) -> int:
        return max(0, self.required - self.owned)


def stack_quantities(objects: Iterable[object]) -> dict[int, int]:
    """Sum all stacks by GID (never mutate protobuf inventory objects)."""
    quantities: dict[int, int] = defaultdict(int)
    for obj in objects:
        item = obj.item
        gid = int(item.gid)
        amount = int(item.quantity)
        if gid > 0 and amount > 0:
            quantities[gid] += amount
    return dict(quantities)


def craft_requirements(crafts: Iterable[tuple[object, int]]) -> dict[int, int]:
    """Combine ingredients across a complete stuff; quantities are per recipe."""
    total: dict[int, int] = defaultdict(int)
    for recipe, count in crafts:
        count = int(count)
        if count <= 0:
            continue
        if len(recipe.ingredientIds) != len(recipe.quantities):
            raise ValueError(f"Invalid recipe for item {recipe.resultId}")
        for gid, quantity in zip(recipe.ingredientIds, recipe.quantities, strict=True):
            if int(quantity) > 0:
                total[int(gid)] += int(quantity) * count
    return dict(total)


def compare_materials(
    required_by_gid: Mapping[int, int],
    bank_objects: Iterable[object],
    inventory_objects: Iterable[object],
) -> list[MaterialBalance]:
    bank = stack_quantities(bank_objects)
    inventory = stack_quantities(inventory_objects)
    return [
        MaterialBalance(int(gid), int(needed), bank.get(gid, 0), inventory.get(gid, 0))
        for gid, needed in sorted(required_by_gid.items())
        if needed > 0
    ]
