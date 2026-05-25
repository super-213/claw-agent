#!/usr/bin/env python3
"""Web UI 入口"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from config import ConfigManager
from core import AgentOrchestrator, ContextCompressor, ConversationManager
from services import LLMClient, CommandExecutor, ConversationStore, TokenUsageEstimator
from services.branch_service import (
    create_session_branch,
    delete_session_branch,
    get_session_tree as get_session_tree_payload,
    switch_session_branch,
)
from services.chat_runner import SessionRunLocks, run_chat, stream_chat_events
from services.dashboard_metrics import DashboardMetrics
from services.message_media import normalize_attachments, normalize_images
from skills import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_DIR = PROJECT_ROOT / "web"


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


app = FastAPI(
    title="Claw Agent API",
    description="Web UI 和会话 API 服务",
    version="1.0.0",
)
app.config = {"TESTING": False}


@app.middleware("http")
async def _set_static_cache_headers(_request: Request, call_next):
    """Disable browser caching for static assets during development."""
    response = await call_next(_request)
    content_type = response.headers.get("content-type", "")
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
    return FileResponse(WEB_DIR / "index.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(WEB_DIR / "dashboard.html")


@app.get("/dashboard/", include_in_schema=False)
def dashboard_slash():
    return FileResponse(WEB_DIR / "dashboard.html")


@app.get("/generated/{filename:path}", include_in_schema=False)
def generated_file(filename: str):
    return _safe_file_response(GENERATED_DIR, filename)


@app.get("/files/{filename:path}", include_in_schema=False)
def files_file(filename: str):
    return _safe_file_response(GENERATED_DIR, filename)


@app.get("/api/sessions", tags=["sessions"])
def list_sessions():
    sessions = store.list_sessions()
    return [asdict(s) for s in sessions]


@app.get("/api/token-usage", tags=["diagnostics"])
def get_token_usage():
    skill_paths = sorted(
        path
        for suffix in SkillRegistry.SUPPORTED_SUFFIXES
        for path in skills_dir.glob(f"*/*{suffix}")
        if not path.name.startswith("._")
    )
    sessions = [
        store.load_session(session.id)
        for session in store.list_sessions()
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


@app.get("/api/dashboard/summary", tags=["dashboard"])
def dashboard_summary(range: str = "all"):
    return _dashboard_metrics().summary(range)


@app.get("/api/dashboard/sessions", tags=["dashboard"])
def dashboard_sessions(
    range: str = "all",
    sort: str = "total_tokens",
    limit: int = 50,
):
    return _dashboard_metrics().sessions(range, sort, limit)


@app.get("/api/dashboard/sessions/{session_id}", tags=["dashboard"])
def dashboard_session_detail(session_id: str):
    try:
        return _dashboard_metrics().session_detail(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)


@app.get("/api/dashboard/tools", tags=["dashboard"])
def dashboard_tools(range: str = "all"):
    return _dashboard_metrics().tools(range)


@app.get("/api/dashboard/word-cloud", tags=["dashboard"])
def dashboard_word_cloud(
    scope: str = "all",
    session_id: str | None = None,
    limit: int = 120,
):
    try:
        return _dashboard_metrics().word_cloud(scope, session_id, limit)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)


@app.get("/api/dashboard/timeseries", tags=["dashboard"])
def dashboard_timeseries(
    metric: str = "tokens",
    range: str = "30d",
):
    return _dashboard_metrics().timeseries(metric, range)


@app.get("/api/skills", tags=["skills"])
def list_skills():
    skills = [_skill_payload(name) for name in skill_registry.list_skills()]
    return {"skills": skills}


@app.get("/api/config", tags=["config"])
def get_config():
    return config.get_public_llm_config()


@app.post("/api/config", tags=["config"])
def update_config(payload: ConfigUpdateRequest | None = Body(default=None)):
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
def reload_skills():
    skills = skill_registry.reload()
    return {
        "ok": True,
        "skills": [_skill_payload(name) for name in skills],
    }


@app.post("/api/skills", tags=["skills"], status_code=201)
def create_skill(payload: SkillCreateRequest | None = Body(default=None)):
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
def create_session(payload: SessionCreateRequest | None = Body(default=None)):
    payload_data = _payload(payload)
    session = store.create_session(agent_prompt, title=payload_data.get("title"))
    return session


@app.get("/api/sessions/{session_id}", tags=["sessions"])
def get_session(session_id: str):
    try:
        session = store.load_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    return session


@app.delete("/api/sessions/{session_id}", tags=["sessions"])
def delete_session(session_id: str):
    try:
        store.delete_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    return {"ok": True}


@app.post("/api/sessions/{session_id}/copy", tags=["sessions"])
def copy_session(session_id: str):
    try:
        session = store.clone_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    return session


@app.post("/api/sessions/{session_id}/branch", tags=["branches"])
def create_branch(
    session_id: str,
    payload: BranchCreateRequest | None = Body(default=None),
):
    payload_data = _payload(payload)
    branch_point_node_id = payload_data.get("branch_point_node_id")

    if not branch_point_node_id:
        return _json({"error": "missing_field", "message": "branch_point_node_id is required"}, 400)

    try:
        return create_session_branch(
            store,
            agent_prompt,
            session_id,
            branch_point_node_id,
        )
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except ValueError as e:
        return _json({"error": "invalid_node_id", "message": str(e)}, 404)


@app.post("/api/sessions/{session_id}/switch", tags=["branches"])
def switch_branch(
    session_id: str,
    payload: BranchSwitchRequest | None = Body(default=None),
):
    payload_data = _payload(payload)
    target_node_id = payload_data.get("target_node_id")

    if not target_node_id:
        return _json({"error": "missing_field", "message": "target_node_id is required"}, 400)

    try:
        return switch_session_branch(
            store,
            agent_prompt,
            session_id,
            target_node_id,
        )
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except ValueError as e:
        return _json({"error": "invalid_node_id", "message": str(e)}, 404)


@app.get("/api/sessions/{session_id}/tree", tags=["branches"])
def get_session_tree(session_id: str):
    try:
        return get_session_tree_payload(store, agent_prompt, session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)


@app.delete("/api/sessions/{session_id}/branch/{node_id}", tags=["branches"])
def delete_branch(session_id: str, node_id: str):
    try:
        return delete_session_branch(store, agent_prompt, session_id, node_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)
    except ValueError as e:
        error_msg = str(e)
        if "不存在" in error_msg:
            return _json({"error": "invalid_node_id", "message": error_msg}, 404)
        # Active path or root node deletion attempts → 400 Bad Request
        return _json({"error": "delete_rejected", "message": error_msg}, 400)


@app.post("/api/chat", tags=["chat"])
async def chat(payload: ChatRequest | None = Body(default=None)):
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


@app.post("/api/chat/stream", tags=["chat"])
async def chat_stream(payload: ChatRequest | None = Body(default=None)):
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
        await asyncio.to_thread(store.load_session, session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)

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


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=False), name="web_static")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("WEB_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )
