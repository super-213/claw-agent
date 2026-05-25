#!/usr/bin/env python3
"""Web UI 入口"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
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
from skills import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_DIR = PROJECT_ROOT / "web"
MAX_MEDIA_ITEMS = 32
MAX_MEDIA_FIELD_LENGTH = 2048


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
    response = await call_next(request)
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
skills_dir = Path(config["skills_dir"])
if not skills_dir.is_absolute():
    skills_dir = PROJECT_ROOT / skills_dir
skill_registry = SkillRegistry(str(skills_dir))
executor = CommandExecutor(
    timeout=config["timeout"],
    cwd=GENERATED_DIR,
    generated_files_dir=GENERATED_DIR,
)


def _clean_text(value: Any, max_length: int = MAX_MEDIA_FIELD_LENGTH) -> str:
    return str(value or "").strip()[:max_length]


def _normalize_images(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("images 必须是数组")

    images: list[dict[str, Any]] = []
    for item in value[:MAX_MEDIA_ITEMS]:
        if isinstance(item, str):
            source = _clean_text(item)
            image = {"url": source}
        elif isinstance(item, dict):
            source = _clean_text(
                item.get("url") or item.get("src") or item.get("path")
            )
            image = {
                "url": source,
                "alt": _clean_text(item.get("alt") or item.get("name"), 200),
                "title": _clean_text(item.get("title"), 200),
            }
            image = {key: val for key, val in image.items() if val}
        else:
            raise ValueError("images 只支持字符串或对象")

        if not image.get("url"):
            raise ValueError("images 中存在空图片地址")
        images.append(image)
    return images


def _normalize_attachments(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("attachments 必须是数组")

    allowed_keys = {
        "name", "url", "src", "path", "type", "mime_type", "mimeType",
        "alt", "title", "size",
    }
    attachments: list[dict[str, Any]] = []
    for item in value[:MAX_MEDIA_ITEMS]:
        if isinstance(item, str):
            attachment = {"url": _clean_text(item)}
        elif isinstance(item, dict):
            attachment = {}
            for key in allowed_keys:
                if key not in item:
                    continue
                raw_value = item[key]
                if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
                    attachment[key] = (
                        raw_value if isinstance(raw_value, (int, float, bool))
                        else _clean_text(raw_value)
                    )
            if "url" not in attachment and attachment.get("src"):
                attachment["url"] = attachment["src"]
            if "url" not in attachment and attachment.get("path"):
                attachment["url"] = attachment["path"]
            attachment = {key: val for key, val in attachment.items() if val not in ("", None)}
        else:
            raise ValueError("attachments 只支持字符串或对象")

        if not attachment:
            raise ValueError("attachments 中存在空附件")
        attachments.append(attachment)
    return attachments


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
        session = store.load_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)

    # Build ConversationManager and load messages to initialize BranchEngine
    conversation = ConversationManager(agent_prompt)
    stored_messages = session.get("messages", [])
    if stored_messages:
        conversation.load_messages(stored_messages, active_node_id=session.get("active_node_id"))

    try:
        result = conversation.create_branch(branch_point_node_id)
    except ValueError as e:
        return _json({"error": "invalid_node_id", "message": str(e)}, 404)

    # Persist all messages (full flat list from branch engine) and updated active_node_id
    all_messages = list(conversation.branch_engine._nodes.values())
    store.save_messages(
        session_id,
        all_messages,
        active_node_id=conversation.active_node_id,
    )

    return {
        "ok": True,
        "branch_node_id": result["branch_node_id"],
        "ancestor_path": result["ancestor_path"],
    }


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
        session = store.load_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)

    # Build ConversationManager and load messages to initialize BranchEngine
    conversation = ConversationManager(agent_prompt)
    stored_messages = session.get("messages", [])
    if stored_messages:
        conversation.load_messages(stored_messages, active_node_id=session.get("active_node_id"))

    try:
        path_messages = conversation.switch_branch(target_node_id)
    except ValueError as e:
        return _json({"error": "invalid_node_id", "message": str(e)}, 404)

    # Persist the updated active_node_id
    all_messages = list(conversation.branch_engine._nodes.values())
    store.save_messages(
        session_id,
        all_messages,
        active_node_id=conversation.active_node_id,
    )

    return {
        "ok": True,
        "active_node_id": target_node_id,
        "messages": path_messages,
    }


@app.get("/api/sessions/{session_id}/tree", tags=["branches"])
def get_session_tree(session_id: str):
    try:
        session = store.load_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)

    # Build ConversationManager and load messages to initialize BranchEngine
    conversation = ConversationManager(agent_prompt)
    stored_messages = session.get("messages", [])
    if stored_messages:
        conversation.load_messages(stored_messages, active_node_id=session.get("active_node_id"))

    if conversation.branch_engine is None:
        return {"nodes": [], "active_node_id": None}

    active_node_id = conversation.active_node_id or ""
    nodes = conversation.branch_engine.get_tree_summary(active_node_id)

    return {
        "nodes": nodes,
        "active_node_id": active_node_id,
    }


@app.delete("/api/sessions/{session_id}/branch/{node_id}", tags=["branches"])
def delete_branch(session_id: str, node_id: str):
    try:
        session = store.load_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)

    # Build ConversationManager and load messages to initialize BranchEngine
    conversation = ConversationManager(agent_prompt)
    stored_messages = session.get("messages", [])
    if stored_messages:
        conversation.load_messages(stored_messages, active_node_id=session.get("active_node_id"))

    if conversation.branch_engine is None:
        return _json({"error": "invalid_node_id", "message": f"节点不存在: {node_id}"}, 404)

    active_node_id = conversation.active_node_id or ""

    try:
        removed_count = conversation.branch_engine.delete_branch(node_id, active_node_id)
    except ValueError as e:
        error_msg = str(e)
        if "不存在" in error_msg:
            return _json({"error": "invalid_node_id", "message": error_msg}, 404)
        # Active path or root node deletion attempts → 400 Bad Request
        return _json({"error": "delete_rejected", "message": error_msg}, 400)

    # Persist updated messages (without the deleted nodes)
    all_messages = list(conversation.branch_engine._nodes.values())
    store.save_messages(
        session_id,
        all_messages,
        active_node_id=active_node_id,
    )

    return {
        "ok": True,
        "removed_count": removed_count,
    }


@app.post("/api/chat", tags=["chat"])
def chat(payload: ChatRequest | None = Body(default=None)):
    payload_data = _payload(payload)
    session_id = payload_data.get("session_id")
    user_message = (payload_data.get("message") or "").strip()
    try:
        images = _normalize_images(payload_data.get("images"))
        attachments = _normalize_attachments(payload_data.get("attachments"))
    except ValueError as e:
        return _json({"error": "invalid_media", "message": str(e)}, 400)

    if not session_id:
        return _json({"error": "missing_session_id"}, 400)
    if not user_message and not images and not attachments:
        return _json({"error": "empty_message"}, 400)

    try:
        session = store.load_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)

    orchestrator = _build_orchestrator()
    conversation = orchestrator.conversation
    stored_messages = session.get("messages", [])
    if stored_messages:
        conversation.load_messages(stored_messages, active_node_id=session.get("active_node_id"))
    conversation.load_summary(
        session.get("summary", ""),
        session.get("summarized_until", 1),
    )

    before_len = len(conversation.get_messages())

    with orchestrator.llm_client:
        orchestrator.process_user_input(
            user_message,
            attachments=attachments,
            images=images,
        )

    messages = conversation.get_messages()
    # Save all nodes (including other branches) to preserve the full tree
    all_messages = (
        list(conversation.branch_engine._nodes.values())
        if conversation.branch_engine is not None
        else messages
    )
    store.save_messages(
        session_id,
        all_messages,
        summary=conversation.get_summary(),
        summarized_until=conversation.get_summarized_until(),
        active_node_id=conversation.active_node_id,
    )

    new_messages = messages[before_len:]

    return {
        "messages": new_messages,
        "session_id": session_id,
    }


def _stream_event(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


@app.post("/api/chat/stream", tags=["chat"])
def chat_stream(payload: ChatRequest | None = Body(default=None)):
    payload_data = _payload(payload)
    session_id = payload_data.get("session_id")
    user_message = (payload_data.get("message") or "").strip()
    try:
        images = _normalize_images(payload_data.get("images"))
        attachments = _normalize_attachments(payload_data.get("attachments"))
    except ValueError as e:
        return _json({"error": "invalid_media", "message": str(e)}, 400)

    if not session_id:
        return _json({"error": "missing_session_id"}, 400)
    if not user_message and not images and not attachments:
        return _json({"error": "empty_message"}, 400)

    try:
        session = store.load_session(session_id)
    except KeyError:
        return _json({"error": "session_not_found"}, 404)

    def generate():
        orchestrator = _build_orchestrator()
        conversation = orchestrator.conversation
        stored_messages = session.get("messages", [])
        if stored_messages:
            conversation.load_messages(stored_messages, active_node_id=session.get("active_node_id"))
        conversation.load_summary(
            session.get("summary", ""),
            session.get("summarized_until", 1),
        )

        before_len = len(conversation.get_messages())
        try:
            with orchestrator.llm_client:
                yield _stream_event({
                    "type": "step",
                    "stage": "request",
                    "message": "开始处理请求",
                })
                for event in orchestrator.process_user_input_stream(
                    user_message,
                    attachments=attachments,
                    images=images,
                ):
                    if event.get("type") != "done":
                        yield _stream_event(event)

            messages = conversation.get_messages()
            yield _stream_event({
                "type": "step",
                "stage": "save",
                "message": "保存会话记录",
            })
            # Save all nodes (including other branches) to preserve the full tree
            all_messages = (
                list(conversation.branch_engine._nodes.values())
                if conversation.branch_engine is not None
                else messages
            )
            store.save_messages(
                session_id,
                all_messages,
                summary=conversation.get_summary(),
                summarized_until=conversation.get_summarized_until(),
                active_node_id=conversation.active_node_id,
            )

            # Extract context_nodes from the last assistant message for the frontend
            new_messages = messages[before_len:]
            context_nodes = None
            for msg in reversed(new_messages):
                if msg.get("role") == "assistant" and "context_nodes" in msg:
                    context_nodes = msg["context_nodes"]
                    break

            done_event = {
                "type": "done",
                "stage": "done",
                "message": "响应完成",
                "messages": new_messages,
                "session_id": session_id,
            }
            if context_nodes is not None:
                done_event["context_nodes"] = context_nodes
            if conversation.active_node_id is not None:
                done_event["active_node_id"] = conversation.active_node_id
            yield _stream_event(done_event)
        except Exception as e:
            yield _stream_event({
                "type": "error",
                "stage": "error",
                "message": str(e),
            })

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=False), name="web_static")


if __name__ == "__main__":
    # FastAPI runs sync route handlers in a threadpool, preserving the current
    # blocking execution model while leaving room to migrate routes to async.
    uvicorn.run(
        app,
        host=os.environ.get("WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
