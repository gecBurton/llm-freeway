from datetime import timedelta

import pytest
from fastapi import HTTPException

from llm_freeway.auth import authenticate_user, create_user_db, get_current_user
from llm_freeway.database import User, create_access_token


def test_authenticate_user(admin_user, admin_user_password, session):
    assert authenticate_user(admin_user.username, admin_user_password, session) == admin_user


def test_authenticate_user_non_existent_user(admin_user, session):
    assert authenticate_user("non-user", "admin", session) is None


def test_authenticate_user_wrong_password(admin_user, session):
    assert authenticate_user(admin_user.username, "password", session) is None


@pytest.mark.anyio
async def test_get_current_user(admin_user: User, session):
    actual_user = await get_current_user(admin_user.get_token(), session)
    assert actual_user == admin_user


@pytest.mark.anyio
async def test_get_current_user_corrupt_token(admin_user: User, session):
    with pytest.raises(HTTPException) as e:
        await get_current_user(admin_user.get_token() + "!", session)
    assert e.value.status_code == 401
    assert e.value.detail == "Could not validate credentials"


@pytest.mark.anyio
async def test_get_current_user_does_not_exist(session):
    new_user = User(username="new.person@example.com")
    with pytest.raises(HTTPException) as e:
        await get_current_user(new_user.get_token(), session)
    assert e.value.status_code == 401
    assert e.value.detail == "Could not validate credentials"


@pytest.mark.anyio
async def test_get_current_user_token_has_no_user(session):
    token = create_access_token(data={}, expires_delta=timedelta(minutes=15))
    with pytest.raises(HTTPException) as e:
        await get_current_user(token, session)
    assert e.value.status_code == 401
    assert e.value.detail == "Could not validate credentials"


def test_create_user_db(admin_user, admin_user_password, session):
    user = create_user_db(
        username=admin_user.username,
        password=admin_user_password,
        is_admin=True,
        tokens_per_minute=10,
        session=session,
    )
    assert user is None
