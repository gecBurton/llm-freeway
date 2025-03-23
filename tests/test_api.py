import json

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from llm_freeway.api import app, get_session


def test_chat_completions(client, payload, admin_user, gpt_4o):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
        headers=admin_user.headers(),
    )

    assert response.status_code == httpx.codes.OK
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

    log_response = client.get(
        "/spend/logs",
        params=dict(response_id=response_json["id"]),
        headers=admin_user.headers(),
    )

    assert log_response.status_code == httpx.codes.OK
    log_response_json = log_response.json()["items"]
    assert isinstance(log_response_json, list)
    assert len(log_response_json) == 1

    assert log_response_json[0]["response_id"] == response_json["id"]
    assert log_response_json[0]["model"] == "gpt-4o"
    assert log_response_json[0]["completion_tokens"] == 20
    assert log_response_json[0]["prompt_tokens"] == 10
    assert log_response_json[0]["user_id"] == str(admin_user.id)


def test_chat_completions_too_many_requests(
    client, payload, user_with_high_rate_low_spend, gpt_4o
):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
        headers=user_with_high_rate_low_spend.headers(),
    )

    assert response.status_code == httpx.codes.TOO_MANY_REQUESTS
    assert response.json() == {"detail": "requests_per_minute=100 exceeded limit=60"}


def test_chat_completions_too_many_tokens(client, payload, user_with_spend, gpt_4o):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
        headers=user_with_spend.headers(),
    )

    assert response.status_code == httpx.codes.TOO_MANY_REQUESTS
    assert response.json() == {"detail": "tokens_per_minute=18000 exceeded limit=1000"}


def test_chat_completions_not_authenticated(client, payload, user_with_spend, gpt_4o):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
    )

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.json() == {"detail": "Not authenticated"}


def test_chat_completions_too_much_usd(
    client, payload, user_with_low_rate_high_spend, gpt_4o
):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
        headers=user_with_low_rate_high_spend.headers(),
    )

    assert response.status_code == httpx.codes.TOO_MANY_REQUESTS
    assert response.json() == {
        "detail": "cost_usd_per_month exceeded=1000.0 exceeded limit=10"
    }


def test_chat_completions_model_doesnt_exist(client, payload, admin_user, gpt_4o):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False, model="my-model"),
        headers=admin_user.headers(),
    )

    assert response.status_code == httpx.codes.NOT_FOUND
    assert response.json() == {"detail": "model=my-model not registered"}


@pytest.mark.anyio
async def test_chat_completions_streaming(
    get_session_override, payload, admin_user, gpt_4o
):
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

    assert log_response.status_code == httpx.codes.OK
    log_response_json = log_response.json()["items"]
    assert isinstance(log_response_json, list)
    assert len(log_response_json) == 1

    assert log_response_json[0]["response_id"] == response_id[0]
    assert log_response_json[0]["model"] == gpt_4o.name
    assert log_response_json[0]["completion_tokens"] == 8
    assert log_response_json[0]["prompt_tokens"] == 9
    assert log_response_json[0]["user_id"] == str(admin_user.id)


def test_get_users(client, admin_user, normal_user):
    response = client.get("/users", headers=normal_user.headers())

    assert response.status_code == httpx.codes.OK
    response_json = response.json()

    users = response_json["items"]
    assert len(users) == 1
    assert users[0]["id"] == str(normal_user.id)


def test_get_users_not_admin(client, admin_user, normal_user):
    response = client.get("/users", headers=admin_user.headers())

    assert response.status_code == httpx.codes.OK
    response_json = response.json()

    users = response_json["items"]
    assert len(users) == 2


def test_create_user(client, admin_user):
    payload = {"username": "some-one", "password": "password", "is_admin": False}

    response = client.post("/users", json=payload, headers=admin_user.headers())

    assert response.status_code == httpx.codes.OK
    response_json = response.json()

    assert not response_json["is_admin"]
    assert response_json["username"] == "some-one"


def test_create_user_not_admin(client, normal_user):
    payload = {"username": "some-one", "password": "password", "is_admin": False}

    response = client.post("/users", json=payload, headers=normal_user.headers())

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.json() == {
        "detail": "you need to be an admin to perform this action"
    }


def test_update_user(client, admin_user, normal_user):
    payload = {"username": "someone-else", "password": "password", "is_admin": True}

    response = client.put(
        f"/users/{normal_user.id}", json=payload, headers=admin_user.headers()
    )

    assert response.status_code == httpx.codes.OK
    response_json = response.json()

    assert response_json["is_admin"]
    assert response_json["username"] == "someone-else"


def test_update_user_not_admin(client, normal_user):
    payload = {"username": "some-one", "password": "password", "is_admin": False}

    response = client.put(
        f"/users/{normal_user.id}", json=payload, headers=normal_user.headers()
    )

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.json() == {
        "detail": "you need to be an admin to perform this action"
    }


def test_update_user_does_not_exist(client, admin_user):
    payload = {"username": "some-one", "password": "password", "is_admin": False}

    response = client.put(
        "/users/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        json=payload,
        headers=admin_user.headers(),
    )

    assert response.status_code == httpx.codes.NOT_FOUND
    assert response.json() == {"detail": "user does not exist"}


def test_delete_user(client, admin_user, normal_user):
    response = client.delete(f"/users/{normal_user.id}", headers=admin_user.headers())

    assert response.status_code == httpx.codes.OK


def test_delete_user_not_admin(client, normal_user):
    response = client.delete(f"/users/{normal_user.id}", headers=normal_user.headers())

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.json() == {
        "detail": "you need to be an admin to perform this action"
    }


def test_token(client, admin_user, admin_user_password):
    payload = {"username": admin_user.username, "password": admin_user_password}

    response = client.post("/token", data=payload)
    response_json = response.json()

    assert response.status_code == httpx.codes.OK
    assert response_json["token_type"] == "bearer"
    token = jwt.decode(
        response_json["access_token"], options={"verify_signature": False}
    )
    assert token["sub"] == admin_user.username


def test_token_fail(client, admin_user):
    payload = {"username": admin_user.username, "password": "wrong password"}

    response = client.post("/token", data=payload)
    response_json = response.json()

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response_json == {"detail": "Incorrect username or password"}


def test_get_models(client, gpt_4o, gpt_4o_mini):
    response = client.get("/models")

    assert response.status_code == httpx.codes.OK
    expected_response = {
        "size": 10,
        "items": [gpt_4o.model_dump(), gpt_4o_mini.model_dump()],
        "page": 1,
    }
    assert response.json() == expected_response


def test_create_model(client, admin_user):
    payload = {
        "input_cost_per_token": 0.1,
        "name": "gpt-4o-mini",
        "output_cost_per_token": 0.2,
    }
    response = client.post("/models", json=payload, headers=admin_user.headers())
    assert response.status_code == httpx.codes.OK
    assert response.json() == payload


def test_create_model_not_admin(client, normal_user):
    payload = {
        "input_cost_per_token": 0.1,
        "name": "gpt-4o-mini",
        "output_cost_per_token": 0.2,
    }
    response = client.post("/models", json=payload, headers=normal_user.headers())
    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.json() == {
        "detail": "you need to be an admin to perform this action"
    }


def test_update_model(client, admin_user, gpt_4o):
    payload = {
        "input_cost_per_token": 12,
        "output_cost_per_token": 13,
    }
    response = client.put(
        f"/models/{gpt_4o.name}", json=payload, headers=admin_user.headers()
    )
    assert response.status_code == httpx.codes.OK
    assert response.json() == dict(payload, name=gpt_4o.name)


def test_update_model_not_admin(client, normal_user, gpt_4o):
    payload = {
        "input_cost_per_token": 12,
        "output_cost_per_token": 13,
    }
    response = client.put(
        f"/models/{gpt_4o.name}", json=payload, headers=normal_user.headers()
    )
    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.json() == {
        "detail": "you need to be an admin to perform this action"
    }


def test_update_model_does_not_exist(client, admin_user):
    payload = {
        "input_cost_per_token": 0.2,
        "output_cost_per_token": 0.1,
    }
    response = client.put(
        "/models/my-fun-model", json=payload, headers=admin_user.headers()
    )
    assert response.status_code == httpx.codes.NOT_FOUND
    assert response.json() == {"detail": "model does not exist"}


def test_delete_model(client, admin_user, gpt_4o):
    response = client.delete(f"/models/{gpt_4o.name}", headers=admin_user.headers())
    assert response.status_code == httpx.codes.OK
    assert response.json() is None


def test_delete_model_not_admin(client, normal_user, gpt_4o):
    response = client.delete(f"/models/{gpt_4o.name}", headers=normal_user.headers())
    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.json() == {
        "detail": "you need to be an admin to perform this action"
    }


def test_delete_model_does_not_exist(client, admin_user):
    response = client.delete("/models/my-fun-model", headers=admin_user.headers())
    assert response.status_code == httpx.codes.NOT_FOUND
    assert response.json() == {"detail": "model does not exist"}
