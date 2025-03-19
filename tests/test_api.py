import json

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from llm_freeway.api import app, get_session


@pytest.mark.anyio
async def test_chat_completions(get_session_override, payload, admin_user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")
    response = test_client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
        headers=admin_user.headers(),
    )

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["choices"] == [
        {
            "finish_reason": "stop",
            "index": 0,
            "message": {
                "content": "hello, how can i help you?",
                "function_call": None,
                "role": "assistant",
                "tool_calls": None,
            },
        }
    ]
    assert response_json["model"] == "gpt-4o"
    assert response_json["object"] == "chat.completion"
    assert response_json["usage"] == {
        "completion_tokens": 20,
        "completion_tokens_details": None,
        "prompt_tokens": 10,
        "prompt_tokens_details": None,
        "total_tokens": 30,
    }

    log_response = test_client.get(
        "/spend/logs",
        params=dict(response_id=response_json["id"]),
        headers=admin_user.headers(),
    )

    assert log_response.status_code == 200
    log_response_json = log_response.json()["logs"]
    assert isinstance(log_response_json, list)
    assert len(log_response_json) == 1

    assert log_response_json[0]["response_id"] == response_json["id"]
    assert log_response_json[0]["model"] == "gpt-4o"
    assert log_response_json[0]["completion_tokens"] == 20
    assert log_response_json[0]["prompt_tokens"] == 10
    assert log_response_json[0]["user_id"] == str(admin_user.id)


@pytest.mark.anyio
async def test_chat_completions_too_many_requests(
    get_session_override, payload, user_with_spend
):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")
    response = test_client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
        headers=user_with_spend.headers(),
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "tokens_per_minute exceeded"}


@pytest.mark.anyio
async def test_chat_completions_streaming(get_session_override, payload, admin_user):
    app.dependency_overrides[get_session] = get_session_override

    records = []
    response_id = []
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        async with ac.stream(
            "POST",
            "/chat/completions",
            json=dict(payload, stream=True),
            headers=admin_user.headers(),
        ) as response:
            async for line in response.aiter_lines():
                if line and line.startswith("data: ") and line != "data: [DONE]":
                    record = json.loads(line.removeprefix("data: "))
                    for choice in record["choices"]:
                        records.append(choice["delta"]["content"])
                    response_id.append(record["id"])
    assert records == [
        "hel",
        "lo,",
        " ho",
        "w c",
        "an ",
        "i h",
        "elp",
        " yo",
        "u?",
        None,
        None,
    ]

    assert len(set(response_id)) == 1

    test_client = TestClient(app=app, base_url="http://test")

    log_response = test_client.get(
        "/spend/logs",
        params=dict(response_id=response_id[0]),
        headers=admin_user.headers(),
    )

    assert log_response.status_code == 200
    log_response_json = log_response.json()["logs"]
    assert isinstance(log_response_json, list)
    assert len(log_response_json) == 1

    assert log_response_json[0]["response_id"] == response_id[0]
    assert log_response_json[0]["model"] == "azure/gpt-4o"
    assert log_response_json[0]["completion_tokens"] == 8
    assert log_response_json[0]["prompt_tokens"] == 9
    assert log_response_json[0]["user_id"] == str(admin_user.id)


def test_get_users(get_session_override, admin_user, user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")

    response = test_client.get("/users", headers=user.headers())

    assert response.status_code == 200, response.text
    response_json = response.json()

    users = response_json["users"]
    assert len(users) == 1
    assert users[0]["id"] == str(user.id)


def test_get_users_not_admin(get_session_override, admin_user, user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")

    response = test_client.get("/users", headers=admin_user.headers())

    assert response.status_code == 200, response.text
    response_json = response.json()

    users = response_json["users"]
    assert len(users) == 2


def test_create_user(get_session_override, admin_user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")

    payload = {"username": "some-one", "password": "password", "is_admin": False}

    response = test_client.post("/users", json=payload, headers=admin_user.headers())

    assert response.status_code == 200
    response_json = response.json()

    assert not response_json["is_admin"]
    assert response_json["username"] == "some-one"


def test_create_user_not_admin(get_session_override, user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")

    payload = {"username": "some-one", "password": "password", "is_admin": False}

    response = test_client.post("/users", json=payload, headers=user.headers())

    assert response.status_code == 400
    assert response.json() == {
        "detail": "you need to be an admin to create, update or delete a user"
    }


def test_update_user(get_session_override, admin_user, user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")

    payload = {"username": "someone-else", "password": "password", "is_admin": True}

    response = test_client.put(
        f"/users/{user.id}", json=payload, headers=admin_user.headers()
    )

    assert response.status_code == 200, response.text
    response_json = response.json()

    assert response_json["is_admin"]
    assert response_json["username"] == "someone-else"


def test_update_user_not_admin(get_session_override, user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")

    payload = {"username": "some-one", "password": "password", "is_admin": False}

    response = test_client.put(
        f"/users/{user.id}", json=payload, headers=user.headers()
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "you need to be an admin to create, update or delete a user"
    }


def test_delete_user(get_session_override, admin_user, user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")

    response = test_client.delete(f"/users/{user.id}", headers=admin_user.headers())

    assert response.status_code == 200


def test_delete_user_not_admin(get_session_override, user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")

    response = test_client.delete(f"/users/{user.id}", headers=user.headers())

    assert response.status_code == 400
    assert response.json() == {
        "detail": "you need to be an admin to create, update or delete a user"
    }


def test_token(get_session_override, user):
    app.dependency_overrides[get_session] = get_session_override

    test_client = TestClient(app=app, base_url="http://test")

    payload = {"username": user.username, "password": "admin"}

    response = test_client.post("/token", data=payload)
    response_json = response.json()

    assert response.status_code == 200, response.text
    assert response_json["token_type"] == "bearer"
    token = jwt.decode(
        response_json["access_token"], options={"verify_signature": False}
    )
    assert token["sub"] == user.username
