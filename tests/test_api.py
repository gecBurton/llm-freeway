import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from llm_freeway.api import app, get_session
from llm_freeway.database import get_models
from tests.conftest import get_headers


def test_chat_completions(client, payload, normal_user, gpt_4o):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
        headers=get_headers(normal_user),
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
        headers=get_headers(normal_user),
    )

    assert log_response.status_code == httpx.codes.OK
    log_response_json = log_response.json()["items"]
    assert isinstance(log_response_json, list)
    assert len(log_response_json) == 1

    assert log_response_json[0]["response_id"] == response_json["id"]
    assert log_response_json[0]["model"] == "gpt-4o"
    assert log_response_json[0]["completion_tokens"] == 20
    assert log_response_json[0]["prompt_tokens"] == 10
    assert log_response_json[0]["user_id"] == str(normal_user.id)


def test_chat_completions_too_many_requests(
    client, payload, user_with_high_rate_low_spend, gpt_4o
):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
        headers=get_headers(user_with_high_rate_low_spend),
    )

    assert response.status_code == httpx.codes.TOO_MANY_REQUESTS
    assert response.json() == {"detail": "requests_per_minute=100 exceeded limit=60"}


def test_chat_completions_too_many_tokens(
    client, payload, user_with_high_tokens_low_spend, gpt_4o
):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False),
        headers=get_headers(user_with_high_tokens_low_spend),
    )

    assert response.status_code == httpx.codes.TOO_MANY_REQUESTS
    assert response.json() == {"detail": "tokens_per_minute=18000 exceeded limit=1000"}


def test_chat_completions_not_authenticated(client, payload, normal_user, gpt_4o):
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
        headers=get_headers(user_with_low_rate_high_spend),
    )

    assert response.status_code == httpx.codes.TOO_MANY_REQUESTS
    assert response.json() == {
        "detail": "cost_usd_per_month exceeded=1000.0 exceeded limit=10"
    }


def test_chat_completions_model_doesnt_exist(
    client,
    payload,
    normal_user,
    gpt_4o,
):
    response = client.post(
        "/chat/completions",
        json=dict(payload, stream=False, model="my-model"),
        headers=get_headers(normal_user),
    )

    assert response.status_code == httpx.codes.NOT_FOUND
    assert response.json() == {"detail": "model=my-model not registered"}


@pytest.mark.anyio
async def test_chat_completions_streaming(
    get_session_override, get_models_override, payload, normal_user, gpt_4o
):
    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_models] = get_models_override

    records = []
    response_id = []
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        async with ac.stream(
            "POST",
            "/chat/completions",
            json=dict(payload, stream=True),
            headers=get_headers(normal_user),
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
        headers=get_headers(normal_user),
    )

    assert log_response.status_code == httpx.codes.OK
    log_response_json = log_response.json()["items"]
    assert isinstance(log_response_json, list)
    assert len(log_response_json) == 1

    assert log_response_json[0]["response_id"] == response_id[0]
    assert log_response_json[0]["model"] == gpt_4o.name
    assert log_response_json[0]["completion_tokens"] == 8
    assert log_response_json[0]["prompt_tokens"] == 9
    assert log_response_json[0]["user_id"] == str(normal_user.id)
