import pytest

from src.application.trainer_use_cases import (
    TrainerPhotoFileKeyError,
    photo_storage_keys_allowed_for_trainer,
    register_photo,
)


def test_photo_storage_keys_allowed() -> None:
    assert photo_storage_keys_allowed_for_trainer(5, "trainers/5/uuid.jpg", "trainers/5/uuid_list.jpg")
    assert photo_storage_keys_allowed_for_trainer(5, "trainers/5/uuid.jpg", None)
    assert not photo_storage_keys_allowed_for_trainer(5, "trainers/6/uuid.jpg", None)
    assert not photo_storage_keys_allowed_for_trainer(5, "trainers/5/../other.jpg", None)
    assert not photo_storage_keys_allowed_for_trainer(5, "", None)


@pytest.mark.asyncio
async def test_register_photo_rejects_foreign_namespace(db_session) -> None:
    from src.application.trainer_use_cases import create_trainer

    tid = await create_trainer(
        db_session,
        profile={"first_name": "A", "last_name": "B", "age": 30},
    )
    with pytest.raises(TrainerPhotoFileKeyError):
        await register_photo(db_session, tid, "trainers/99999/other.jpg")
