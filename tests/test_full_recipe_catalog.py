"""Source-only unit tests for the complete DOFUS recipe book."""
from types import SimpleNamespace

from src.services.full_recipe_catalog import (
    build_full_recipe_catalog,
    normalized_recipe_query,
)


def recipe(result_id, name_id, job_id, ingredient_ids, amounts, level=200):
    return SimpleNamespace(
        resultId=result_id,
        resultNameId=str(name_id),
        jobId=job_id,
        resultLevel=level,
        ingredientIds=ingredient_ids,
        quantities=amounts,
    )


def test_all_jobs_are_included_not_only_harvesters():
    recipes = [
        recipe(100, 1, 25, [40, 41], [4, 3]),
        recipe(101, 2, 31, [42], [20]),
        recipe(102, 3, 13, [43], [7]),
    ]
    index = build_full_recipe_catalog(
        recipes,
        {1: "Coiffe A", 2: "Anneau B", 3: "Bottes C"},
        {25: "Tailleur", 31: "Bijoutier", 13: "Cordonnier"},
    )
    assert set(index) == {100, 101, 102}
    assert index[100].job_name == "Tailleur"
    assert index[101].recipe.quantities == [20]
    assert index[102].level == 200


def test_skips_corrupt_recipes_without_dropping_valid_others():
    good = recipe(100, 1, 25, [40], [4])
    mismatched = recipe(101, 2, 25, [40, 41], [4])
    empty = recipe(102, 3, 25, [], [])
    zero_quantity = recipe(103, 4, 25, [42], [0])
    index = build_full_recipe_catalog(
        [good, mismatched, empty, zero_quantity],
        {1: "Coiffe A"},
        {25: "Tailleur"},
    )
    assert list(index) == [100]


def test_unknown_translation_is_reported_without_fake_names():
    index = build_full_recipe_catalog(
        [recipe(100, 99999, 50, [40], [1])],
        {},
        {},
    )
    assert index[100].name == "Objet #100"
    assert index[100].job_name == "Métier #50"


def test_french_search_is_accent_insensitive():
    assert normalized_recipe_query("ÉPÉE   Légendaire") == "epee legendaire"
    assert "epee" in normalized_recipe_query("Épée des Glaces")


def test_no_profession_filter_in_source_catalog():
    professions = range(1, 21)
    recipes = [recipe(100 + job_id, job_id, job_id, [600], [1]) for job_id in professions]
    index = build_full_recipe_catalog(
        recipes,
        {job_id: f"Objet {job_id}" for job_id in professions},
        {job_id: f"Métier {job_id}" for job_id in professions},
    )
    assert len(index) == 20
