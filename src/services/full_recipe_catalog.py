"""Catalog of all craft recipes extracted from the installed DOFUS client build.

This is separate from automatic crafting support: the Atelier can plan any
well-formed recipe, including tailor, jeweller, smith, shoemaker and other jobs.
"""
from collections.abc import Iterable, Mapping
from functools import cache
import unicodedata

from DBDofusUnity.dofus_unity_reader.data_center.data_reader import DataReader
from DBDofusUnity.dofus_unity_reader.data_center.i18n import I18N
from DBDofusUnity.dofus_unity_reader.models.datas.recipe_root import RecipeItem
from src.services.display_catalog import RecipeEntry


def normalized_recipe_query(value: str) -> str:
    """Case-, accent-, and whitespace-insensitive search for French items."""
    text = unicodedata.normalize("NFKD", value).casefold()
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).split())


def build_full_recipe_catalog(
    recipes: Iterable[RecipeItem],
    names_by_id: Mapping[int, str],
    jobs_by_id: Mapping[int, str],
) -> dict[int, RecipeEntry]:
    """Index all valid source recipes by result GID, with no profession filter."""
    result: dict[int, RecipeEntry] = {}
    for recipe in recipes:
        item_id = int(recipe.resultId)
        if item_id <= 0 or not recipe.ingredientIds:
            continue
        if len(recipe.ingredientIds) != len(recipe.quantities):
            continue
        if any(int(count) <= 0 for count in recipe.quantities):
            continue
        if any(int(ingredient) <= 0 for ingredient in recipe.ingredientIds):
            continue
        try:
            name_id = int(recipe.resultNameId)
        except (TypeError, ValueError):
            name_id = -1
        name = names_by_id.get(name_id) or f"Objet #{item_id}"
        job_id = int(recipe.jobId)
        job_name = jobs_by_id.get(job_id) or f"Métier #{job_id}"
        result[item_id] = RecipeEntry(
            recipe=recipe, name=str(name), job_name=str(job_name), level=int(recipe.resultLevel)
        )
    return result


@cache
def load_full_recipe_catalog() -> dict[int, RecipeEntry]:
    """Source of truth: RecipesDataRoot.json, not a filtered craft action list."""
    game_data = DataReader()
    names = I18N().name_by_id
    jobs = {
        int(job_id): names.get(int(job.nameId), f"Métier #{job_id}")
        for job_id, job in game_data.job_by_id.items()
    }
    return build_full_recipe_catalog(game_data.recipes, names, jobs)
