import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from litellm import completion
from pydantic import BaseModel, Field
from sqlmodel import Session, SQLModel, select
from starlette import status
from starlette.responses import StreamingResponse

from llm_freeway.auth import get_admin_user, get_current_user, get_token
from llm_freeway.database import (
    LLM,
    EventLog,
    Token,
    User,
    UserDB,
    authenticate_user,
    engine,
    get_session,
    pwd_context,
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

    model = session.get(LLM, body.model)
    if model is None:
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


@app.post("/token")
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[Session, Depends(get_session)],
) -> Token:
    user = authenticate_user(form_data.username, form_data.password, session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Token(access_token=get_token(user), token_type="bearer")


class UserResponse(BaseModel):
    page: int
    size: int
    items: list[User]


@app.get(path="/users", tags=["users"])
def get_users(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    page: int = Query(1, ge=0),
    size: int = Query(10, gt=0),
) -> UserResponse:
    if not current_user.is_admin:
        data = [current_user]
    else:
        skip = (page - 1) * size
        data = session.exec(select(UserDB).offset(skip).limit(size)).all()

    return UserResponse(page=page, size=size, items=data)


class UserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False


@app.post(path="/users", tags=["users"])
def create_user(
    admin_user: Annotated[User, Depends(get_admin_user)],
    session: Annotated[Session, Depends(get_session)],
    user: UserRequest,
) -> User:
    user_to_create = UserDB(
        username=user.username,
        is_admin=user.is_admin,
        hashed_password=pwd_context.hash(user.password),
    )

    session.add(user_to_create)
    session.commit()
    session.refresh(user_to_create)

    return user_to_create


@app.put(path="/users/{user_id}", tags=["users"])
def update_user(
    admin_user: Annotated[User, Depends(get_admin_user)],
    session: Annotated[Session, Depends(get_session)],
    user_id: UUID,
    user: UserRequest,
) -> User:
    user_to_update: UserDB = session.get(UserDB, user_id)
    if user_to_update is None:
        raise HTTPException(
            status_code=404,
            detail="user does not exist",
        )

    user_to_update.username = user.username
    user_to_update.hashed_password = pwd_context.hash(user.password)
    user_to_update.is_admin = user.is_admin

    session.add(user_to_update)
    session.commit()
    session.refresh(user_to_update)

    return user_to_update


@app.delete(path="/users/{user_id}", tags=["users"])
def delete_user(
    admin_user: Annotated[User, Depends(get_admin_user)],
    session: Annotated[Session, Depends(get_session)],
    user_id: UUID,
) -> None:
    user_to_delete: UserDB = session.exec(
        select(UserDB).where(UserDB.id == user_id)
    ).one()
    session.delete(user_to_delete)
    session.commit()
