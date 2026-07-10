from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from agenthub.db.repositories import GoalNotFoundError, get_goal_record, link_goal_session

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1, max_length=100_000)
    session_key: str = Field(min_length=1, max_length=300)
    channel: str = Field(default="web", min_length=1, max_length=64)
    external_user_id: str | None = Field(default=None, max_length=200)
    goal_id: str | None = None
    session_id: str | None = Field(default=None, max_length=300)
    relation: Literal["origin", "attached", "delivery"] = "attached"


async def _hermes_request(
    request: Request,
    method: str,
    path: str,
    *,
    payload: dict[str, object] | None = None,
    session_key: str | None = None,
) -> httpx.Response:
    settings = request.app.state.settings
    headers: dict[str, str] = {}
    if settings.hermes_api_key is not None:
        headers["Authorization"] = f"Bearer {settings.hermes_api_key.get_secret_value()}"
        if session_key is not None:
            headers["X-Hermes-Session-Key"] = session_key
    transport = getattr(request.app.state, "hermes_http_transport", None)
    try:
        async with httpx.AsyncClient(
            base_url=settings.hermes_api_base_url,
            timeout=30,
            transport=transport,
        ) as client:
            return await client.request(method, path, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Hermes API is unavailable: {exc}") from exc


@router.post("", status_code=202)
async def start_chat_run(payload: ChatRunRequest, request: Request) -> dict[str, object]:
    if payload.goal_id is not None:
        with request.app.state.session_factory() as session:
            try:
                get_goal_record(session, payload.goal_id)
            except GoalNotFoundError as exc:
                raise HTTPException(status_code=404, detail="goal not found") from exc
            link_goal_session(
                session,
                goal_id=payload.goal_id,
                session_key=payload.session_key,
                channel=payload.channel,
                external_user_id=payload.external_user_id,
                relation=payload.relation,
            )
    upstream_payload: dict[str, object] = {"input": payload.input}
    upstream_payload["session_id"] = payload.session_id or payload.session_key
    response = await _hermes_request(
        request,
        "POST",
        "/v1/runs",
        payload=upstream_payload,
        session_key=payload.session_key,
    )
    if response.is_error:
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": response.status_code, "body": response.text[:2000]},
        )
    result = response.json()
    return {
        **result,
        "goal_id": payload.goal_id,
        "session_key": payload.session_key,
        "channel": payload.channel,
    }


@router.get("/runs/{run_id}")
async def get_chat_run(run_id: str, request: Request) -> dict[str, object]:
    response = await _hermes_request(request, "GET", f"/v1/runs/{run_id}")
    if response.is_error:
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": response.status_code, "body": response.text[:2000]},
        )
    return response.json()
