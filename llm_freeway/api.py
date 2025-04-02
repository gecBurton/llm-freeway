import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from litellm import completion
from pydantic import BaseModel, Field
from sqlmodel import Session, SQLModel, select
from starlette import status
from starlette.responses import StreamingResponse

from llm_freeway.auth import get_current_user
from llm_freeway.database import (
    EventLog,
    LLMConfig,
    User,
    engine,
    get_models,
    get_session,
)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(lifespan=lifespan)


class ChatMessage(BaseModel):
    role: Literal["user", "ai", "system"] = Field(default="user")
    content: str = Field(examples=["tell me a joke"])


class ChatRequest(BaseModel):
    model: str = Field(examples=["azure/gpt-4o"])
    messages: list[ChatMessage]
    stream: bool = False
    mock_response: str | None = Field(default=None)


@app.post(path="/chat/completions")
async def stream_response(
    body: ChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    llm_config: Annotated[LLMConfig, Depends(get_models)],
) -> StreamingResponse:
    spend = current_user.get_spend(session)

    if spend.requests > current_user.requests_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"requests_per_minute={spend.requests} exceeded limit={current_user.requests_per_minute}",
        )

    total_tokens = spend.prompt_tokens + spend.completion_tokens
    if total_tokens > current_user.tokens_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"tokens_per_minute={total_tokens} exceeded limit={current_user.tokens_per_minute}",
        )

    if spend.cost_usd and spend.cost_usd > current_user.cost_usd_per_month:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"cost_usd_per_month exceeded={spend.cost_usd} exceeded limit={current_user.cost_usd_per_month}",
        )

    try:
        model = next(model for model in llm_config.models if model.name == body.model)
    except StopIteration:
        raise HTTPException(
            status_code=httpx.codes.NOT_FOUND,
            detail=f"model={body.model} not registered",
        )

    vertex_credentials = os.getenv("VERTEX_CREDENTIALS", None)

    if not body.stream:
        model_response = completion(
            vertex_credentials=vertex_credentials, **body.model_dump()
        )
        log = EventLog(
            user_id=current_user.id,
            model=model.name,
            response_id=model_response.id,
            prompt_tokens=model_response.usage["prompt_tokens"],
            completion_tokens=model_response.usage["completion_tokens"],
            cost_usd=model_response.usage["prompt_tokens"] * model.input_cost_per_token
            + model_response.usage["completion_tokens"] * model.output_cost_per_token,
        )
        session.add(log)
        session.commit()
        return model_response

    async def event_generator():
        stream_wrapper = completion(
            vertex_credentials=vertex_credentials,
            stream_options={"include_usage": True},
            **body.model_dump(),
        )
        prompt_tokens = 0
        completion_tokens = 0
        for part in stream_wrapper:
            if hasattr(part, "usage"):
                prompt_tokens += part.usage["prompt_tokens"]
                completion_tokens += part.usage["completion_tokens"]
            yield f"data: {part.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

        cost_usd = (
            prompt_tokens * model.input_cost_per_token
            + completion_tokens * model.output_cost_per_token
        )

        _log = EventLog(
            user_id=current_user.id,
            model=model.name,
            response_id=stream_wrapper.response_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )
        session.add(_log)
        session.commit()

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


class EventLogResponse(BaseModel):
    items: list[EventLog]
    page: int
    size: int


@app.get(path="/spend/logs")
def spend_logs(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    user_id: str | None = None,
    response_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    page: int = Query(1, ge=0),
    size: int = Query(10, gt=0),
) -> EventLogResponse:
    query = select(EventLog)
    if not current_user.is_admin:
        query = query.where(EventLog.user_id == current_user.id)
    if user_id:
        query = query.where(EventLog.user_id == user_id)
    if response_id:
        query = query.where(EventLog.response_id == response_id)
    if start_date:
        query = query.where(EventLog.timestamp >= start_date)
    if end_date:
        query = query.where(EventLog.timestamp < end_date)

    skip = size * (page - 1)
    items = session.exec(
        query.order_by(EventLog.timestamp).offset(skip).limit(size)
    ).all()
    return EventLogResponse(items=items, page=page, size=size)
