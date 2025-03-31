import pytest
from fastapi import HTTPException

from llm_freeway.auth import get_current_user
from llm_freeway.database import User


@pytest.mark.anyio
async def test_get_current_user(admin_user: User):
    actual_user = await get_current_user(admin_user.get_token())
    assert actual_user == admin_user


@pytest.mark.anyio
async def test_get_current_user_corrupt_token(admin_user: User):
    with pytest.raises(HTTPException) as e:
        await get_current_user(admin_user.get_token() + "!")
    assert e.value.status_code == 401
    assert e.value.detail == "Could not validate credentials"


@pytest.mark.anyio
async def test_get_current_user_does_not_exist():
    new_user = User(username="new.person@example.com")
    with pytest.raises(HTTPException) as e:
        await get_current_user(new_user.get_token())
    assert e.value.status_code == 401
    assert e.value.detail == "Could not validate credentials"
