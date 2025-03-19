from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from litellm import completion
from pydantic import BaseModel, Field
from sqlmodel import Session, SQLModel, select
from starlette import status
from starlette.responses import StreamingResponse

from llm_freeway.auth import (
    authenticate_user,
    create_or_update_user,
    get_current_user,
    pwd_context,
)
from llm_freeway.database import EventLog, Token, User, UserDB, engine, get_session

app = FastAPI()


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        create_or_update_user("admin", "admin", True, 10_0000, session)


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
):
    spend = current_user.get_spend(session)
    if spend.requests > current_user.requests_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="requests_per_minute exceeded",
        )

    if spend.prompt_tokens + spend.completion_tokens > current_user.tokens_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="tokens_per_minute exceeded",
        )

    if not body.stream:
        response = completion(**body.model_dump())
        log = EventLog(
            user_id=current_user.id,
            model=response.model,
            response_id=response.id,
            prompt_tokens=response.usage["prompt_tokens"],
            completion_tokens=response.usage["completion_tokens"],
        )
        session.add(log)
        session.commit()
        return response

    async def event_generator():
        _response = completion(
            stream_options={"include_usage": True}, **body.model_dump()
        )
        for part in _response:
            if hasattr(part, "usage"):
                _log = EventLog(
                    user_id=current_user.id,
                    model=part.model,
                    response_id=part.id,
                    prompt_tokens=part.usage["prompt_tokens"],
                    completion_tokens=part.usage["completion_tokens"],
                )
                session.add(_log)
            yield f"data: {part.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"
        session.commit()

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


class EventLogResponse(BaseModel):
    logs: list[EventLog]


@app.get(path="/spend/logs")
def spend_logs(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    user_id: str | None = None,
    response_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, gt=0),
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
    logs = session.exec(query.offset(skip).limit(limit)).all()
    return EventLogResponse(logs=logs, skip=skip, limit=limit)


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
    return user.get_token()


class UserResponse(BaseModel):
    skip: int
    limit: int
    users: list[User]


@app.get(path="/users", tags=["users"])
def get_users(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    skip: int = Query(0, ge=0),
    limit: int = Query(10, gt=0),
) -> UserResponse:
    if not current_user.is_admin:
        users = [current_user]
    else:
        users = session.exec(select(UserDB).offset(skip).limit(limit)).all()

    return UserResponse(skip=skip, limit=limit, users=users)


class UserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False


@app.post(path="/users", tags=["users"])
def create_user(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    user: UserRequest,
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=400,
            detail="you need to be an admin to create, update or delete a user",
        )

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
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    user_id: UUID,
    user: UserRequest,
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=400,
            detail="you need to be an admin to create, update or delete a user",
        )

    user_to_update: UserDB = session.exec(
        select(UserDB).where(UserDB.id == user_id)
    ).one()

    user_to_update.username = user.username
    user_to_update.hashed_password = pwd_context.hash(user.password)
    user_to_update.is_admin = user.is_admin

    session.add(user_to_update)
    session.commit()
    session.refresh(user_to_update)

    return user_to_update


@app.delete(path="/users/{user_id}", tags=["users"])
def delete_user(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    user_id: UUID,
) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=400,
            detail="you need to be an admin to create, update or delete a user",
        )

    user_to_delete: UserDB = session.exec(
        select(UserDB).where(UserDB.id == user_id)
    ).one()
    session.delete(user_to_delete)
    session.commit()
