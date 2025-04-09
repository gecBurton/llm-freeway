from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from llm_freeway.auth import get_current_user, get_token
from llm_freeway.database import User
from tests.test_api import skip_keycloak


@pytest.mark.anyio
async def test_get_current_user(normal_user: User, session):
    actual_user = await get_current_user(get_token(normal_user), session)
    assert User(**actual_user.model_dump()) == User(**normal_user.model_dump())


@pytest.mark.anyio
async def test_get_current_user_corrupt_token(normal_user: User, session):
    with pytest.raises(HTTPException) as e:
        await get_current_user(get_token(normal_user) + "!", session)
    assert e.value.status_code == httpx.codes.UNAUTHORIZED
    assert e.value.detail == "Could not validate credentials"


@skip_keycloak
@pytest.mark.anyio
async def test_get_current_user_does_not_exist(session):
    new_user = User(username="new.person@example.com", id=uuid4())
    with pytest.raises(HTTPException) as e:
        await get_current_user(get_token(new_user), session)
    assert e.value.status_code == httpx.codes.UNAUTHORIZED
    assert e.value.detail == "Could not validate credentials"
