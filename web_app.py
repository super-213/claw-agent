#!/usr/bin/env python3
"""Web UI 入口"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
import os
from pathlib import Path
from typing import Any
import uuid

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

from config import ConfigManager
from core import AgentOrchestrator, ContextCompressor, ConversationManager
from services import LLMClient, CommandExecutor, ConversationStore, HomeDataService, TokenUsageEstimator, UserStore
from services.access_control import (
    can_delete_session,
    can_manage_users,
    can_read_session,
    can_write_session,
    normalize_sharing,
)
from services.auth_service import AuthSessionStore
from services.branch_service import (
    create_session_branch,
    delete_session_branch,
    get_session_tree as get_session_tree_payload,
    switch_session_branch,
)
from services.chat_runner import SessionRunLocks, run_chat, stream_chat_events, stream_event
from services.dashboard_metrics import DashboardMetrics
from services.message_media import normalize_attachments, normalize_images
from skills import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parent


class ConfigUpdateRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class SkillCreateRequest(BaseModel):
    name: str | None = None
    content: str | None = None


class SessionCreateRequest(BaseModel):
    title: str | None = None


class BranchCreateRequest(BaseModel):
    branch_point_node_id: str | None = None


class BranchSwitchRequest(BaseModel):
    target_node_id: str | None = None


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str | None = None
    images: Any = None
    attachments: Any = None


class BootstrapAdminRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    display_name: str | None = None


class LoginRequest(BaseModel):
    username: str | None = None
    password: str | None = None


class UserCreateRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    display_name: str | None = None
    role: str | None = "user"
    status: str | None = "active"


class UserUpdateRequest(BaseModel):
    username: str | None = None
    display_name: str | None = None
    role: str | None = None
    status: str | None = None


class PasswordResetRequest(BaseModel):
    password: str | None = None


class ShareUpdateRequest(BaseModel):
    scope: str | None = None
    user_ids: list[str] | None = None
    permission: str | None = None


class InventoryConsumeRequest(BaseModel):
    quantity: float | int | None = None


class ReminderSnoozeRequest(BaseModel):
    minutes: int | None = 10


app = FastAPI(
    title="Claw Agent API",
    description="Web UI 和会话 API 服务",
    version="1.0.0",
)
app.config = {"TESTING": False}
AUTH_COOKIE_NAME = "claw_session"


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = str(exc.detail or "")
    if exc.status_code == 401:
        return _error("unauthorized", 401)
    if exc.status_code == 403:
        return _error("forbidden", 403)
    return _error(detail or "http_error", exc.status_code)


@app.middleware("http")
async def _set_static_cache_headers(_request: Request, call_next):
    """Disable browser caching for static assets during development."""
    response = await call_next(_request)
    content_type = response.headers.get("content-type", "")
    if _request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    if content_type and (
        "text/css" in content_type
        or "javascript" in content_type
        or "text/html" in content_type
    ):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


class _LegacyCompatResponse:
    """Small response shim for the existing get_json()-style tests."""

    def __init__(self, response):
        self._response = response

    def get_json(self, *args, **kwargs):
        return self._response.json()

    def get_data(self, as_text: bool = False):
        data = self._response.content
        return data.decode(self._response.encoding or "utf-8") if as_text else data

    @property
    def data(self):
        return self._response.content

    def __getattr__(self, name: str):
        return getattr(self._response, name)


class _LegacyCompatTestClient:
    """Expose app.test_client() while tests are migrated to FastAPI idioms."""

    def __init__(self, fastapi_app: FastAPI):
        from fastapi.testclient import TestClient

        self._client = TestClient(fastapi_app)

    def __enter__(self):
        self._client.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._client.__exit__(exc_type, exc, tb)

    def request(self, method: str, url: str, **kwargs):
        return _LegacyCompatResponse(self._client.request(method, url, **kwargs))

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def open(self, url: str, method: str = "GET", **kwargs):
        return self.request(method, url, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


def _test_client():
    return _LegacyCompatTestClient(app)


app.test_client = _test_client


def _json(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status_code)


def _payload(model: BaseModel | None) -> dict[str, Any]:
    return model.model_dump() if model is not None else {}


def _test_user() -> dict[str, Any]:
    return {
        "id": "test-admin",
        "username": "test-admin",
        "display_name": "Test Admin",
        "role": "admin",
        "status": "active",
    }


def _error(error: str, status_code: int, message: str | None = None) -> JSONResponse:
    payload: dict[str, Any] = {"error": error}
    if message:
        payload["message"] = message
    return _json(payload, status_code)


def _safe_file_response(directory: Path, filename: str) -> FileResponse:
    requested_path = (directory / filename).resolve()
    try:
        requested_path.relative_to(directory)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not Found")
    if not requested_path.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(requested_path)


config = ConfigManager()
home_data_dir = Path(config["home_data_dir"])
if not home_data_dir.is_absolute():
    home_data_dir = PROJECT_ROOT / home_data_dir
home_service = HomeDataService(
    home_data_dir,
    timezone_name=config["home_timezone"],
    quiet_start=config["home_notification_quiet_start"],
    quiet_end=config["home_notification_quiet_end"],
)
agent_path = Path(config["agent_file"])
if not agent_path.is_absolute():
    agent_path = PROJECT_ROOT / agent_path
generated_dir = Path(config["generated_files_dir"])
if not generated_dir.is_absolute():
    generated_dir = PROJECT_ROOT / generated_dir
GENERATED_DIR = generated_dir.resolve()
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
agent_prompt = agent_path.read_text(encoding="utf-8")
agent_prompt += (
    "\n\n## 文件生成目录\n\n"
    f"- 当前命令工作目录固定为：{GENERATED_DIR}\n"
    "- 所有新建、导出、下载、转换、保存的文件都必须写入当前工作目录，"
    "也就是 GENERATED_FILES_DIR/FILES_DIR 指向的目录。\n"
    "- 生成文件时直接使用文件名或子目录名，例如 report.pdf、images/chart.png；"
    "不要再额外加 files/ 前缀。\n"
    "- 如果工具必须使用绝对路径，只能使用 $GENERATED_FILES_DIR/文件名 "
    "或 $FILES_DIR/文件名；不要写入项目根目录、用户主目录、/tmp 或其他目录。\n"
    f"- 如需读取或检查项目源码，使用 PROJECT_ROOT 环境变量：{PROJECT_ROOT}\n"
    "- 完成时请给出生成文件相对该目录的文件名或 /generated/<文件名>，不要返回本地绝对路径。\n"
)

conversation_root = Path(config["conversation_dir"])
if not conversation_root.is_absolute():
    conversation_root = PROJECT_ROOT / conversation_root
token_estimator = TokenUsageEstimator(config["token_encoding"])
store = ConversationStore(conversation_root, token_estimator=token_estimator)
user_file = Path(config["user_file"])
if not user_file.is_absolute():
    user_file = PROJECT_ROOT / user_file
user_store = UserStore(user_file)
auth_sessions = AuthSessionStore()
session_run_locks = SessionRunLocks()
skills_dir = Path(config["skills_dir"])
if not skills_dir.is_absolute():
    skills_dir = PROJECT_ROOT / skills_dir
skill_registry = SkillRegistry(str(skills_dir))
executor = CommandExecutor(
    timeout=config["timeout"],
    cwd=GENERATED_DIR,
    generated_files_dir=GENERATED_DIR,
)


def _ensure_env_admin() -> None:
    """Optionally create the first admin from environment variables."""
    if user_store.has_admin():
        return
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if not username or not password:
        return
    admin = user_store.create_user(
        username=username,
        password=password,
        display_name=os.environ.get("ADMIN_DISPLAY_NAME") or username,
        role="admin",
    )
    store.ensure_owner_for_legacy_sessions(admin["id"])


def _bootstrap_completed() -> bool:
    _ensure_env_admin()
    return user_store.has_admin()


async def current_user(request: Request) -> dict[str, Any] | None:
    if app.config.get("TESTING"):
        return _test_user()
    token = request.cookies.get(AUTH_COOKIE_NAME)
    user_id = auth_sessions.get_user_id(token)
    if not user_id:
        return None
    user = user_store.get_user(user_id)
    if not user or user.get("status") != "active":
        return None
    return user


async def require_user(request: Request) -> dict[str, Any]:
    user = await current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


async def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if not can_manage_users(user):
        raise HTTPException(status_code=403, detail="forbidden")
    return user


def _response_with_login_cookie(user: dict[str, Any]) -> JSONResponse:
    token = auth_sessions.create(user["id"])
    response = _json({"ok": True, "user": user})
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=72 * 60 * 60,
    )
    return response


def _clear_login_cookie(response: Response) -> None:
    auth_sessions.delete(response.headers.get(AUTH_COOKIE_NAME))
    response.delete_cookie(AUTH_COOKIE_NAME)


def _load_authorized_session(
    session_id: str,
    user: dict[str, Any],
    *,
    write: bool = False,
    delete: bool = False,
) -> dict[str, Any]:
    session = store.load_session(session_id)
    allowed = (
        can_delete_session(user, session)
        if delete
        else can_write_session(user, session)
        if write
        else can_read_session(user, session)
    )
    if not allowed:
        raise PermissionError(session_id)
    return session


def _visible_session_metas(user: dict[str, Any]) -> list[dict[str, Any]]:
    visible = []
    for meta in store.list_sessions():
        payload = asdict(meta)
        if user.get("role") == "admin":
            visible.append(payload)
            continue
        try:
            session = store.load_session(meta.id)
        except KeyError:
            continue
        if can_read_session(user, session):
            visible.append(payload)
    return visible


def _dashboard_metrics_for_user(user: dict[str, Any]) -> DashboardMetrics:
    if user.get("role") == "admin":
        return _dashboard_metrics()
    visible_ids = {item["id"] for item in _visible_session_metas(user)}

    class _ScopedStore:
        def list_sessions(self):
            return [
                meta for meta in store.list_sessions()
                if meta.id in visible_ids
            ]

        def load_session(self, session_id: str):
            if session_id not in visible_ids:
                raise KeyError(session_id)
            return store.load_session(session_id)

    return DashboardMetrics(
        _ScopedStore(),
        token_estimator,
        agent_path=agent_path,
        agent_prompt=agent_prompt,
        skills_dir=skills_dir,
    )


_ensure_env_admin()


def _skill_payload(skill_name: str) -> dict:
    skill = skill_registry.get(skill_name)
    if not skill:
        return {"name": skill_name}
    
    file_path = getattr(skill, "file_path", None)
    payload = {"name": skill_name}
    if file_path:
        stat = Path(file_path).stat()
        payload.update({
            "path": str(file_path),
            "bytes": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return payload


def _build_orchestrator() -> AgentOrchestrator:
    llm_client = LLMClient(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        timeout=config["timeout"],
    )
    conversation = ConversationManager(agent_prompt)
    context_compressor = ContextCompressor(
        llm_client=llm_client,
        max_context_chars=config["context_max_chars"],
        recent_messages=config["context_recent_messages"],
        summary_target_chars=config["summary_target_chars"],
        summary_input_chars=config["summary_input_chars"],
    )
    return AgentOrchestrator(
        llm_client=llm_client,
        conversation=conversation,
        skill_registry=skill_registry,
        executor=executor,
        context_compressor=context_compressor,
    )


@app.get("/", include_in_schema=False)
def index():
    return {"service": "Claw Agent API"}


@app.get("/generated/{filename:path}", include_in_schema=False)
def generated_file(filename: str):
    return _safe_file_response(GENERATED_DIR, filename)


@app.get("/files/{filename:path}", include_in_schema=False)
def files_file(filename: str):
    return _safe_file_response(GENERATED_DIR, filename)


@app.get("/api/auth/bootstrap-status", tags=["auth"])
def auth_bootstrap_status():
    return {"admin_exists": _bootstrap_completed()}


@app.post("/api/auth/bootstrap-admin", tags=["auth"])
def auth_bootstrap_admin(payload: BootstrapAdminRequest | None = Body(default=None)):
    if _bootstrap_completed():
        return _error("admin_already_exists", 409)
    payload_data = _payload(payload)
    try:
        user = user_store.create_user(
            username=payload_data.get("username") or "",
            password=payload_data.get("password") or "",
            display_name=payload_data.get("display_name"),
            role="admin",
        )
    except ValueError as e:
        return _error(str(e), 400)
    store.ensure_owner_for_legacy_sessions(user["id"])
    user_store.mark_login(user["id"])
    return _response_with_login_cookie(user)


@app.get("/api/auth/usernames", tags=["auth"])
def auth_usernames():
    if not _bootstrap_completed():
        return {"usernames": []}
    return {"usernames": user_store.list_usernames()}


@app.post("/api/auth/login", tags=["auth"])
def auth_login(payload: LoginRequest | None = Body(default=None)):
    if not _bootstrap_completed():
        return _error("admin_required", 409)
    payload_data = _payload(payload)
    user = user_store.verify_password(
        payload_data.get("username") or "",
        payload_data.get("password") or "",
    )
    if not user:
        return _error("invalid_credentials", 401)
    user_store.mark_login(user["id"])
    return _response_with_login_cookie(user)


@app.post("/api/auth/logout", tags=["auth"])
def auth_logout(request: Request, response: Response):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    auth_sessions.delete(token)
    response.delete_cookie(AUTH_COOKIE_NAME)
    return {"ok": True}


@app.get("/api/auth/me", tags=["auth"])
async def auth_me(user: dict[str, Any] | None = Depends(current_user)):
    if not user:
        return _error("unauthorized", 401)
    return {"user": user}


@app.get("/api/admin/users", tags=["admin"])
def admin_list_users(_admin: dict[str, Any] = Depends(require_admin)):
    return {"users": user_store.list_users()}


@app.get("/api/users", tags=["users"])
def list_shareable_users(_user: dict[str, Any] = Depends(require_user)):
    return {
        "users": [
            user for user in user_store.list_users()
            if user.get("status") == "active"
        ]
    }


@app.post("/api/admin/users", tags=["admin"], status_code=201)
def admin_create_user(
    payload: UserCreateRequest | None = Body(default=None),
    _admin: dict[str, Any] = Depends(require_admin),
):
    payload_data = _payload(payload)
    try:
        user = user_store.create_user(
            username=payload_data.get("username") or "",
            password=payload_data.get("password") or "",
            display_name=payload_data.get("display_name"),
            role=payload_data.get("role") or "user",
            status=payload_data.get("status") or "active",
        )
    except ValueError as e:
        return _error(str(e), 400)
    return _json({"ok": True, "user": user}, 201)


@app.get("/api/admin/users/{user_id}", tags=["admin"])
def admin_get_user(user_id: str, _admin: dict[str, Any] = Depends(require_admin)):
    user = user_store.get_user(user_id)
    if not user or user.get("status") == "deleted":
        return _error("user_not_found", 404)
    return {"user": user}


@app.patch("/api/admin/users/{user_id}", tags=["admin"])
def admin_update_user(
    user_id: str,
    payload: UserUpdateRequest | None = Body(default=None),
    _admin: dict[str, Any] = Depends(require_admin),
):
    try:
        user = user_store.update_user(user_id, **_payload(payload))
    except KeyError:
        return _error("user_not_found", 404)
    except ValueError as e:
        return _error(str(e), 400)
    return {"ok": True, "user": user}


@app.delete("/api/admin/users/{user_id}", tags=["admin"])
def admin_delete_user(user_id: str, _admin: dict[str, Any] = Depends(require_admin)):
    try:
        user_store.delete_user(user_id)
    except KeyError:
        return _error("user_not_found", 404)
    except ValueError as e:
        return _error(str(e), 400)
    return {"ok": True}


@app.post("/api/admin/users/{user_id}/reset-password", tags=["admin"])
def admin_reset_password(
    user_id: str,
    payload: PasswordResetRequest | None = Body(default=None),
    _admin: dict[str, Any] = Depends(require_admin),
):
    payload_data = _payload(payload)
    try:
        user = user_store.reset_password(user_id, payload_data.get("password") or "")
    except KeyError:
        return _error("user_not_found", 404)
    except ValueError as e:
        return _error(str(e), 400)
    return {"ok": True, "user": user}


@app.get("/api/admin/users/{user_id}/usage", tags=["admin"])
def admin_user_usage(user_id: str, _admin: dict[str, Any] = Depends(require_admin)):
    user = user_store.get_user(user_id)
    if not user or user.get("status") == "deleted":
        return _error("user_not_found", 404)
    sessions = []
    for meta in store.list_sessions():
        try:
            session = store.load_session(meta.id)
        except KeyError:
            continue
        if session.get("owner_user_id") == user_id:
            sessions.append(session)
    token_total = sum((session.get("token_usage") or {}).get("total_tokens", 0) for session in sessions)
    message_count = sum(len(session.get("messages", [])) for session in sessions)
    return {
        "user": user,
        "usage": {
            "session_count": len(sessions),
            "message_count": message_count,
            "total_tokens": token_total,
            "last_active_at": max(
                (session.get("updated_at") or session.get("created_at") or "" for session in sessions),
                default=user.get("last_login_at") or user.get("created_at") or "",
            ),
        },
    }


@app.get("/api/sessions", tags=["sessions"])
def list_sessions(user: dict[str, Any] = Depends(require_user)):
    return _visible_session_metas(user)


@app.get("/api/token-usage", tags=["diagnostics"])
def get_token_usage(user: dict[str, Any] = Depends(require_user)):
    skill_paths = sorted(
        path
        for suffix in SkillRegistry.SUPPORTED_SUFFIXES
        for path in skills_dir.glob(f"*/*{suffix}")
        if not path.name.startswith("._")
    )
    visible_ids = {item["id"] for item in _visible_session_metas(user)}
    sessions = [
        store.load_session(session.id)
        for session in store.list_sessions()
        if session.id in visible_ids
    ]
    return {
        "estimated": True,
        "encoding": token_estimator.encoding_name,
        "system_prompt": {
            "path": str(agent_path),
            "tokens": token_estimator.count_text(agent_prompt),
            "characters": len(agent_prompt),
            "bytes": len(agent_prompt.encode("utf-8")),
        },
        "skills": token_estimator.summarize_files(skill_paths),
        "sessions": [
            {
                "id": session.get("id"),
                "title": session.get("title"),
                "token_usage": session.get("token_usage"),
            }
            for session in sessions
        ],
    }


def _dashboard_metrics() -> DashboardMetrics:
    return DashboardMetrics(
        store,
        token_estimator,
        agent_path=agent_path,
        agent_prompt=agent_prompt,
        skills_dir=skills_dir,
    )


def _append_direct_chat_response(session_id: str, user_message: str, assistant_message: str) -> list[dict[str, Any]]:
    session = store.load_session(session_id)
    messages = list(session.get("messages") or [])
    now = datetime.now().isoformat()
    parent_id = session.get("active_node_id") or (messages[-1].get("node_id") if messages else None)
    user_node_id = uuid.uuid4().hex
    assistant_node_id = uuid.uuid4().hex
    new_messages = [
        {
            "role": "user",
            "content": user_message,
            "ts": now,
            "node_id": user_node_id,
            "parent_id": parent_id,
        },
        {
            "role": "assistant",
            "content": assistant_message,
            "ts": now,
            "node_id": assistant_node_id,
            "parent_id": user_node_id,
        },
    ]
    store.save_messages(
        session_id,
        messages + new_messages,
        summary=session.get("summary", ""),
        summarized_until=session.get("summarized_until", 1),
        active_node_id=assistant_node_id,
        summarized_nodes=session.get("summarized_nodes"),
    )
    return new_messages


async def _home_scheduler_loop() -> None:
    interval = max(5, int(config["home_scheduler_interval_seconds"]))
    while True:
        try:
            await asyncio.to_thread(home_service.process_due_reminders)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[home_scheduler] {exc}")
        await asyncio.sleep(interval)


@app.on_event("startup")
async def _start_home_scheduler() -> None:
    if app.config.get("TESTING"):
        return
    app.state.home_scheduler_task = asyncio.create_task(_home_scheduler_loop())


@app.on_event("shutdown")
async def _stop_home_scheduler() -> None:
    task = getattr(app.state, "home_scheduler_task", None)
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@app.get("/api/dashboard/summary", tags=["dashboard"])
def dashboard_summary(
    range: str = "all",
    user: dict[str, Any] = Depends(require_user),
):
    return _dashboard_metrics_for_user(user).summary(range)


@app.get("/api/dashboard/sessions", tags=["dashboard"])
def dashboard_sessions(
    range: str = "all",
    sort: str = "total_tokens",
    limit: int = 50,
    user: dict[str, Any] = Depends(require_user),
):
    return _dashboard_metrics_for_user(user).sessions(range, sort, limit)


@app.get("/api/dashboard/sessions/{session_id}", tags=["dashboard"])
def dashboard_session_detail(
    session_id: str,
    user: dict[str, Any] = Depends(require_user),
):
    try:
        return _dashboard_metrics_for_user(user).session_detail(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)


@app.get("/api/dashboard/tools", tags=["dashboard"])
def dashboard_tools(
    range: str = "all",
    user: dict[str, Any] = Depends(require_user),
):
    return _dashboard_metrics_for_user(user).tools(range)


@app.get("/api/dashboard/word-cloud", tags=["dashboard"])
def dashboard_word_cloud(
    scope: str = "all",
    session_id: str | None = None,
    limit: int = 120,
    user: dict[str, Any] = Depends(require_user),
):
    try:
        return _dashboard_metrics_for_user(user).word_cloud(scope, session_id, limit)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)


@app.get("/api/dashboard/timeseries", tags=["dashboard"])
def dashboard_timeseries(
    metric: str = "tokens",
    range: str = "30d",
    user: dict[str, Any] = Depends(require_user),
):
    return _dashboard_metrics_for_user(user).timeseries(metric, range)


@app.get("/api/dashboard/users", tags=["dashboard"])
def dashboard_users(_admin: dict[str, Any] = Depends(require_admin)):
    rows = []
    users = {
        user["id"]: user
        for user in user_store.list_users()
        if user.get("status") != "deleted"
    }
    by_user: dict[str, list[dict[str, Any]]] = {user_id: [] for user_id in users}
    for meta in store.list_sessions():
        try:
            session = store.load_session(meta.id)
        except KeyError:
            continue
        owner_id = session.get("owner_user_id")
        if owner_id in by_user:
            by_user[owner_id].append(session)
    for user_id, user_info in users.items():
        sessions = by_user.get(user_id, [])
        token_total = sum(
            (session.get("token_usage") or {}).get("total_tokens", 0)
            for session in sessions
        )
        message_count = sum(len(session.get("messages", [])) for session in sessions)
        rows.append({
            "user": user_info,
            "session_count": len(sessions),
            "message_count": message_count,
            "total_tokens": token_total,
            "last_active_at": max(
                (session.get("updated_at") or session.get("created_at") or "" for session in sessions),
                default=user_info.get("last_login_at") or user_info.get("created_at") or "",
            ),
        })
    rows.sort(key=lambda row: row["total_tokens"], reverse=True)
    return {"users": rows}


@app.get("/api/dashboard/home/tasks/summary", tags=["dashboard"])
def dashboard_home_tasks_summary(_user: dict[str, Any] = Depends(require_user)):
    return home_service.dashboard_task_summary()


@app.get("/api/dashboard/home/tasks/timeseries", tags=["dashboard"])
def dashboard_home_tasks_timeseries(days: int = 30, _user: dict[str, Any] = Depends(require_user)):
    return home_service.dashboard_task_timeseries(days)


@app.get("/api/dashboard/home/tasks", tags=["dashboard"])
def dashboard_home_tasks(
    status: str | None = None,
    type: str | None = None,
    recipient_user_id: str | None = None,
    channel: str | None = None,
    next_run_before: str | None = None,
    _user: dict[str, Any] = Depends(require_user),
):
    return home_service.dashboard_tasks(
        status=status,
        type=type,
        recipient_user_id=recipient_user_id,
        channel=channel,
        next_run_before=next_run_before,
    )


@app.get("/api/dashboard/home/notifications/summary", tags=["dashboard"])
def dashboard_home_notifications_summary(_user: dict[str, Any] = Depends(require_user)):
    return home_service.dashboard_notifications_summary()


@app.get("/api/home/household", tags=["home"])
def home_household(_user: dict[str, Any] = Depends(require_user)):
    return home_service.household()


@app.patch("/api/home/household", tags=["home"])
def home_update_household(payload: dict[str, Any] | None = Body(default=None), admin: dict[str, Any] = Depends(require_admin)):
    return home_service.update_household(payload or {}, admin)


@app.get("/api/home/activity-log", tags=["home"])
def home_activity_log(limit: int = 100, _user: dict[str, Any] = Depends(require_user)):
    return {"activity": home_service.activity_log(limit)}


@app.get("/api/home/inventory/expiring", tags=["home"])
def home_inventory_expiring(
    days: int = 3,
    location: str | None = None,
    _user: dict[str, Any] = Depends(require_user),
):
    try:
        return home_service.expiring_items(days=days, location=location)
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.get("/api/home/inventory", tags=["home"])
def home_inventory(
    location: str | None = None,
    category: str | None = None,
    status: str | None = None,
    expires_before: str | None = None,
    _user: dict[str, Any] = Depends(require_user),
):
    try:
        return home_service.list_inventory(
            location=location,
            category=category,
            status=status,
            expires_before=expires_before,
        )
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.get("/api/home/inventory/{location}", tags=["home"])
def home_inventory_location(
    location: str,
    category: str | None = None,
    status: str | None = None,
    expires_before: str | None = None,
    _user: dict[str, Any] = Depends(require_user),
):
    try:
        return home_service.list_inventory(
            location=location,
            category=category,
            status=status,
            expires_before=expires_before,
        )
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.post("/api/home/inventory/{location}/items", tags=["home"], status_code=201)
def home_inventory_add_item(
    location: str,
    payload: dict[str, Any] | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    try:
        return _json(home_service.add_inventory_item(location, payload or {}, user), 201)
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.patch("/api/home/inventory/{location}/items/{item_id}", tags=["home"])
def home_inventory_update_item(
    location: str,
    item_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    try:
        return home_service.update_inventory_item(location, item_id, payload or {}, user)
    except KeyError:
        return _json({"error": "item_not_found"}, 404)
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.delete("/api/home/inventory/{location}/items/{item_id}", tags=["home"])
def home_inventory_delete_item(location: str, item_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.delete_inventory_item(location, item_id, user)
    except KeyError:
        return _json({"error": "item_not_found"}, 404)
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.post("/api/home/inventory/{location}/items/{item_id}/consume", tags=["home"])
def home_inventory_consume_item(
    location: str,
    item_id: str,
    payload: InventoryConsumeRequest | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    try:
        return home_service.consume_inventory_item(location, item_id, _payload(payload).get("quantity"), user)
    except KeyError:
        return _json({"error": "item_not_found"}, 404)
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.post("/api/home/inventory/{location}/items/{item_id}/restore", tags=["home"])
def home_inventory_restore_item(location: str, item_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.restore_inventory_item(location, item_id, user)
    except KeyError:
        return _json({"error": "item_not_found"}, 404)
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.get("/api/home/reminders", tags=["home"])
def home_reminders(
    status: str | None = None,
    type: str | None = None,
    recipient_user_id: str | None = None,
    channel: str | None = None,
    next_run_before: str | None = None,
    _user: dict[str, Any] = Depends(require_user),
):
    return home_service.list_reminders(
        status=status,
        type=type,
        recipient_user_id=recipient_user_id,
        channel=channel,
        next_run_before=next_run_before,
    )


@app.post("/api/home/reminders", tags=["home"], status_code=201)
def home_create_reminder(
    payload: dict[str, Any] | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    try:
        return _json(home_service.create_reminder(payload or {}, user), 201)
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.get("/api/home/reminders/{reminder_id}", tags=["home"])
def home_get_reminder(reminder_id: str, _user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.get_reminder(reminder_id)
    except KeyError:
        return _json({"error": "reminder_not_found"}, 404)


@app.patch("/api/home/reminders/{reminder_id}", tags=["home"])
def home_update_reminder(
    reminder_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    try:
        return home_service.update_reminder(reminder_id, payload or {}, user)
    except KeyError:
        return _json({"error": "reminder_not_found"}, 404)
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.delete("/api/home/reminders/{reminder_id}", tags=["home"])
def home_delete_reminder(reminder_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.delete_reminder(reminder_id, user)
    except KeyError:
        return _json({"error": "reminder_not_found"}, 404)


@app.post("/api/home/reminders/{reminder_id}/complete", tags=["home"])
def home_complete_reminder(reminder_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.complete_reminder(reminder_id, user)
    except KeyError:
        return _json({"error": "reminder_not_found"}, 404)


@app.post("/api/home/reminders/{reminder_id}/snooze", tags=["home"])
def home_snooze_reminder(
    reminder_id: str,
    payload: ReminderSnoozeRequest | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    try:
        return home_service.snooze_reminder(reminder_id, int(_payload(payload).get("minutes") or 10), user)
    except KeyError:
        return _json({"error": "reminder_not_found"}, 404)


@app.post("/api/home/reminders/{reminder_id}/cancel", tags=["home"])
def home_cancel_reminder(reminder_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.cancel_reminder(reminder_id, user)
    except KeyError:
        return _json({"error": "reminder_not_found"}, 404)


@app.get("/api/home/schedules", tags=["home"])
def home_schedules(_user: dict[str, Any] = Depends(require_user)):
    return home_service.list_schedules()


@app.post("/api/home/schedules", tags=["home"], status_code=201)
def home_create_schedule(payload: dict[str, Any] | None = Body(default=None), user: dict[str, Any] = Depends(require_user)):
    return _json(home_service.create_schedule(payload or {}, user), 201)


@app.patch("/api/home/schedules/{schedule_id}", tags=["home"])
def home_update_schedule(schedule_id: str, payload: dict[str, Any] | None = Body(default=None), user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.update_schedule(schedule_id, payload or {}, user)
    except KeyError:
        return _json({"error": "schedule_not_found"}, 404)


@app.delete("/api/home/schedules/{schedule_id}", tags=["home"])
def home_delete_schedule(schedule_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.delete_schedule(schedule_id, user)
    except KeyError:
        return _json({"error": "schedule_not_found"}, 404)


@app.get("/api/home/notifications", tags=["home"])
def home_notifications(unread_only: bool = False, limit: int = 100, _user: dict[str, Any] = Depends(require_user)):
    return home_service.notifications(unread_only=unread_only, limit=limit)


@app.post("/api/home/notifications/{notification_id}/read", tags=["home"])
def home_notification_read(notification_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.mark_notification_read(notification_id, user)
    except KeyError:
        return _json({"error": "notification_not_found"}, 404)


@app.post("/api/home/notifications/read-all", tags=["home"])
def home_notification_read_all(user: dict[str, Any] = Depends(require_user)):
    return home_service.mark_all_notifications_read(user)


@app.get("/api/push/vapid-public-key", tags=["push"])
def push_vapid_public_key(_user: dict[str, Any] = Depends(require_user)):
    return home_service.vapid_public_key()


@app.get("/api/push/subscriptions", tags=["push"])
def push_subscriptions(user: dict[str, Any] = Depends(require_user)):
    return home_service.list_push_subscriptions(user)


@app.post("/api/push/subscriptions", tags=["push"], status_code=201)
def push_create_subscription(payload: dict[str, Any] | None = Body(default=None), user: dict[str, Any] = Depends(require_user)):
    try:
        return _json(home_service.add_push_subscription(payload or {}, user), 201)
    except ValueError as e:
        return _json({"error": str(e)}, 400)


@app.patch("/api/push/subscriptions/{subscription_id}", tags=["push"])
def push_update_subscription(
    subscription_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    try:
        return home_service.update_push_subscription(subscription_id, payload or {}, user)
    except KeyError:
        return _json({"error": "subscription_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)


@app.delete("/api/push/subscriptions/{subscription_id}", tags=["push"])
def push_delete_subscription(subscription_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.delete_push_subscription(subscription_id, user)
    except KeyError:
        return _json({"error": "subscription_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)


@app.post("/api/push/test", tags=["push"])
def push_test(payload: dict[str, Any] | None = Body(default=None), user: dict[str, Any] = Depends(require_user)):
    try:
        return home_service.send_test_push(payload or {}, user)
    except KeyError:
        return _json({"error": "subscription_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)


@app.get("/api/skills", tags=["skills"])
def list_skills(_user: dict[str, Any] = Depends(require_user)):
    skills = [_skill_payload(name) for name in skill_registry.list_skills()]
    return {"skills": skills}


@app.get("/api/config", tags=["config"])
def get_config(_user: dict[str, Any] = Depends(require_user)):
    return config.get_public_llm_config()


@app.post("/api/config", tags=["config"])
def update_config(
    payload: ConfigUpdateRequest | None = Body(default=None),
    _admin: dict[str, Any] = Depends(require_admin),
):
    payload_data = _payload(payload)
    try:
        public_config = config.update_llm_config(
            api_key=payload_data.get("api_key"),
            base_url=payload_data.get("base_url"),
            model=payload_data.get("model"),
        )
    except ValueError as e:
        return _json({"error": "invalid_config", "message": str(e)}, 400)

    return {"ok": True, "config": public_config}


@app.post("/api/skills/reload", tags=["skills"])
def reload_skills(_user: dict[str, Any] = Depends(require_user)):
    skills = skill_registry.reload()
    return {
        "ok": True,
        "skills": [_skill_payload(name) for name in skills],
    }


@app.post("/api/skills", tags=["skills"], status_code=201)
def create_skill(
    payload: SkillCreateRequest | None = Body(default=None),
    _admin: dict[str, Any] = Depends(require_admin),
):
    payload_data = _payload(payload)
    name = (payload_data.get("name") or "").strip()
    content = (payload_data.get("content") or "").strip()
    
    try:
        skill = skill_registry.create_skill(name, content)
    except FileExistsError:
        return _json({"error": "skill_exists", "message": f"技能已存在：{name}"}, 409)
    except ValueError as e:
        return _json({"error": "invalid_skill", "message": str(e)}, 400)
    
    return _json({
        "ok": True,
        "skill": _skill_payload(skill.name),
    }, 201)


@app.post("/api/sessions", tags=["sessions"])
def create_session(
    payload: SessionCreateRequest | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    payload_data = _payload(payload)
    session = store.create_session(
        agent_prompt,
        title=payload_data.get("title"),
        owner_user_id=user.get("id"),
    )
    return session


@app.get("/api/sessions/{session_id}", tags=["sessions"])
def get_session(session_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        session = _load_authorized_session(session_id, user)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)
    return session


@app.delete("/api/sessions/{session_id}", tags=["sessions"])
def delete_session(session_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        _load_authorized_session(session_id, user, delete=True)
        store.delete_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)
    return {"ok": True}


@app.post("/api/sessions/{session_id}/copy", tags=["sessions"])
def copy_session(session_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        _load_authorized_session(session_id, user)
        session = store.clone_session(session_id, owner_user_id=user.get("id"))
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)
    return session


@app.get("/api/sessions/{session_id}/share", tags=["sessions"])
def get_session_share(session_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        session = _load_authorized_session(session_id, user)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)
    return {"sharing": session.get("sharing") or {"scope": "private", "user_ids": [], "permission": "write"}}


@app.patch("/api/sessions/{session_id}/share", tags=["sessions"])
def update_session_share(
    session_id: str,
    payload: ShareUpdateRequest | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    try:
        session = _load_authorized_session(session_id, user)
        if user.get("role") != "admin" and session.get("owner_user_id") != user.get("id"):
            return _json({"error": "forbidden"}, 403)
        sharing = normalize_sharing(_payload(payload))
        updated = store.update_sharing(session_id, sharing)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)
    except ValueError as e:
        return _json({"error": str(e)}, 400)
    return {"ok": True, "sharing": updated.get("sharing")}


@app.post("/api/sessions/{session_id}/branch", tags=["branches"])
def create_branch(
    session_id: str,
    payload: BranchCreateRequest | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    payload_data = _payload(payload)
    branch_point_node_id = payload_data.get("branch_point_node_id")

    if not branch_point_node_id:
        return _json({"error": "missing_field", "message": "branch_point_node_id is required"}, 400)

    try:
        _load_authorized_session(session_id, user, write=True)
        return create_session_branch(
            store,
            agent_prompt,
            session_id,
            branch_point_node_id,
        )
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)
    except ValueError as e:
        if "尚未对话" in str(e):
            return _json({"error": "branch_rejected", "message": str(e)}, 400)
        return _json({"error": "invalid_node_id", "message": str(e)}, 404)


@app.post("/api/sessions/{session_id}/switch", tags=["branches"])
def switch_branch(
    session_id: str,
    payload: BranchSwitchRequest | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    payload_data = _payload(payload)
    target_node_id = payload_data.get("target_node_id")

    if not target_node_id:
        return _json({"error": "missing_field", "message": "target_node_id is required"}, 400)

    try:
        _load_authorized_session(session_id, user, write=True)
        return switch_session_branch(
            store,
            agent_prompt,
            session_id,
            target_node_id,
        )
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)
    except ValueError as e:
        return _json({"error": "invalid_node_id", "message": str(e)}, 404)


@app.get("/api/sessions/{session_id}/tree", tags=["branches"])
def get_session_tree(session_id: str, user: dict[str, Any] = Depends(require_user)):
    try:
        _load_authorized_session(session_id, user)
        return get_session_tree_payload(store, agent_prompt, session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)


@app.delete("/api/sessions/{session_id}/branch/{node_id}", tags=["branches"])
def delete_branch(
    session_id: str,
    node_id: str,
    user: dict[str, Any] = Depends(require_user),
):
    try:
        _load_authorized_session(session_id, user, write=True)
        return delete_session_branch(store, agent_prompt, session_id, node_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)
    except ValueError as e:
        error_msg = str(e)
        if "不存在" in error_msg:
            return _json({"error": "invalid_node_id", "message": error_msg}, 404)
        # Active path or root node deletion attempts → 400 Bad Request
        return _json({"error": "delete_rejected", "message": error_msg}, 400)


@app.post("/api/chat", tags=["chat"])
async def chat(
    payload: ChatRequest | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    payload_data = _payload(payload)
    session_id = payload_data.get("session_id")
    user_message = (payload_data.get("message") or "").strip()
    try:
        images = normalize_images(payload_data.get("images"))
        attachments = normalize_attachments(payload_data.get("attachments"))
    except ValueError as e:
        return _json({"error": "invalid_media", "message": str(e)}, 400)

    if not session_id:
        return _json({"error": "missing_session_id"}, 400)
    if not user_message and not images and not attachments:
        return _json({"error": "empty_message"}, 400)

    try:
        await asyncio.to_thread(_load_authorized_session, session_id, user, write=True)
        if not images and not attachments:
            home_reply = await asyncio.to_thread(
                home_service.handle_home_chat_intent,
                user_message,
                user,
                session_id,
            )
            if home_reply:
                messages = await asyncio.to_thread(
                    _append_direct_chat_response,
                    session_id,
                    user_message,
                    home_reply,
                )
                return {"messages": messages, "session_id": session_id}
        return await run_chat(
            store=store,
            build_orchestrator=_build_orchestrator,
            session_run_locks=session_run_locks,
            session_id=session_id,
            user_message=user_message,
            attachments=attachments,
            images=images,
        )
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)


@app.post("/api/chat/stream", tags=["chat"])
async def chat_stream(
    payload: ChatRequest | None = Body(default=None),
    user: dict[str, Any] = Depends(require_user),
):
    payload_data = _payload(payload)
    session_id = payload_data.get("session_id")
    user_message = (payload_data.get("message") or "").strip()
    try:
        images = normalize_images(payload_data.get("images"))
        attachments = normalize_attachments(payload_data.get("attachments"))
    except ValueError as e:
        return _json({"error": "invalid_media", "message": str(e)}, 400)

    if not session_id:
        return _json({"error": "missing_session_id"}, 400)
    if not user_message and not images and not attachments:
        return _json({"error": "empty_message"}, 400)

    try:
        await asyncio.to_thread(_load_authorized_session, session_id, user, write=True)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except PermissionError:
        return _json({"error": "forbidden"}, 403)

    if not images and not attachments:
        home_reply = await asyncio.to_thread(
            home_service.handle_home_chat_intent,
            user_message,
            user,
            session_id,
        )
        if home_reply:
            async def direct_home_stream():
                yield stream_event({
                    "type": "step",
                    "stage": "home",
                    "message": "家庭记忆已处理",
                })
                messages = await asyncio.to_thread(
                    _append_direct_chat_response,
                    session_id,
                    user_message,
                    home_reply,
                )
                yield stream_event({
                    "type": "model_start",
                    "stage": "home",
                    "iteration": 1,
                    "model": "home-agent",
                    "message_count": 1,
                })
                yield stream_event({
                    "type": "model_delta",
                    "stage": "home",
                    "iteration": 1,
                    "delta": home_reply,
                })
                yield stream_event({
                    "type": "model_done",
                    "stage": "home",
                    "iteration": 1,
                    "content": home_reply,
                })
                yield stream_event({
                    "type": "done",
                    "stage": "done",
                    "message": "响应完成",
                    "messages": messages,
                    "session_id": session_id,
                })

            return StreamingResponse(
                direct_home_stream(),
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    return StreamingResponse(
        stream_chat_events(
            store=store,
            build_orchestrator=_build_orchestrator,
            session_run_locks=session_run_locks,
            session_id=session_id,
            user_message=user_message,
            attachments=attachments,
            images=images,
        ),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("WEB_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )
