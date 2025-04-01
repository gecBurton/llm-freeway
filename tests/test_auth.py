import httpx
import pytest
from fastapi import HTTPException
from requests import HTTPError

from llm_freeway.auth import get_current_user
from llm_freeway.database import User


@pytest.mark.anyio
async def test_get_current_user(normal_user: User):
    actual_user = await get_current_user(normal_user.get_token())
    normal_user.password = None
    assert actual_user == normal_user


@pytest.mark.anyio
async def test_get_current_user_corrupt_token(normal_user: User):
    with pytest.raises(HTTPException) as e:
        await get_current_user(normal_user.get_token() + "!")
    assert e.value.status_code == httpx.codes.UNAUTHORIZED
    assert e.value.detail == "Could not validate credentials"


@pytest.mark.anyio
async def test_get_current_user_does_not_exist():
    new_user = User(username="new.person@example.com")
    with pytest.raises(HTTPError) as e:
        await get_current_user(new_user.get_token())
    assert (
        e.value.args[0]
        == "404 Client Error: Not Found for url: http://localhost:8080/realms/tmp-realm/protocol/openid-connect/token"
    )
