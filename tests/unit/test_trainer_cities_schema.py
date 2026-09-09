"""TASK-058 EDGE-002: schema — at most one is_primary per trainer."""

from src.infrastructure.db.models import trainer_cities_table


def test_trainer_cities_partial_unique_primary_index() -> None:
    indexes = {idx.name: idx for idx in trainer_cities_table.indexes}
    assert "uq_trainer_cities_one_primary" in indexes
    idx = indexes["uq_trainer_cities_one_primary"]
    assert idx.unique is True
    assert [col.name for col in idx.columns] == ["trainer_id"]
