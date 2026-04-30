#!/usr/bin/env python3
"""Web UI 入口"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request

from config import ConfigManager
from core import AgentOrchestrator, ContextCompressor, ConversationManager
from services import LLMClient, CommandExecutor, ConversationStore, TokenUsageEstimator
from skills import SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_DIR = PROJECT_ROOT / "web"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
app.json.ensure_ascii = False

config = ConfigManager()
agent_path = Path(config["agent_file"])
if not agent_path.is_absolute():
    agent_path = PROJECT_ROOT / agent_path
agent_prompt = agent_path.read_text(encoding="utf-8")

conversation_root = Path(config["conversation_dir"])
if not conversation_root.is_absolute():
    conversation_root = PROJECT_ROOT / conversation_root
token_estimator = TokenUsageEstimator(config["token_encoding"])
store = ConversationStore(conversation_root, token_estimator=token_estimator)
skills_dir = Path(config["skills_dir"])
if not skills_dir.is_absolute():
    skills_dir = PROJECT_ROOT / skills_dir
skill_registry = SkillRegistry(str(skills_dir))
executor = CommandExecutor(timeout=config["timeout"])


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


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/sessions")
def list_sessions():
    sessions = store.list_sessions()
    return jsonify([asdict(s) for s in sessions])


@app.get("/api/token-usage")
def get_token_usage():
    skill_paths = sorted(
        path
        for path in skills_dir.glob("*/*.md")
        if not path.name.startswith("._")
    )
    sessions = [
        store.load_session(session.id)
        for session in store.list_sessions()
    ]
    return jsonify({
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
    })


@app.get("/api/skills")
def list_skills():
    skills = [_skill_payload(name) for name in skill_registry.list_skills()]
    return jsonify({"skills": skills})


@app.post("/api/skills/reload")
def reload_skills():
    skills = skill_registry.reload()
    return jsonify({
        "ok": True,
        "skills": [_skill_payload(name) for name in skills],
    })


@app.post("/api/skills")
def create_skill():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    content = (payload.get("content") or "").strip()
    
    try:
        skill = skill_registry.create_skill(name, content)
    except FileExistsError:
        return jsonify({"error": "skill_exists", "message": f"技能已存在：{name}"}), 409
    except ValueError as e:
        return jsonify({"error": "invalid_skill", "message": str(e)}), 400
    
    return jsonify({
        "ok": True,
        "skill": _skill_payload(skill.name),
    }), 201


@app.post("/api/sessions")
def create_session():
    payload = request.get_json(silent=True) or {}
    session = store.create_session(agent_prompt, title=payload.get("title"))
    return jsonify(session)


@app.get("/api/sessions/<session_id>")
def get_session(session_id: str):
    try:
        session = store.load_session(session_id)
    except KeyError:
        return jsonify({"error": "session_not_found"}), 404
    return jsonify(session)


@app.delete("/api/sessions/<session_id>")
def delete_session(session_id: str):
    try:
        store.delete_session(session_id)
    except KeyError:
        return jsonify({"error": "session_not_found"}), 404
    return jsonify({"ok": True})


@app.post("/api/sessions/<session_id>/copy")
def copy_session(session_id: str):
    try:
        session = store.clone_session(session_id)
    except KeyError:
        return jsonify({"error": "session_not_found"}), 404
    return jsonify(session)


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    session_id = payload.get("session_id")
    user_message = (payload.get("message") or "").strip()

    if not session_id:
        return jsonify({"error": "missing_session_id"}), 400
    if not user_message:
        return jsonify({"error": "empty_message"}), 400

    try:
        session = store.load_session(session_id)
    except KeyError:
        return jsonify({"error": "session_not_found"}), 404

    orchestrator = _build_orchestrator()
    conversation = orchestrator.conversation
    stored_messages = session.get("messages", [])
    if stored_messages:
        conversation.load_messages(stored_messages)
    conversation.load_summary(
        session.get("summary", ""),
        session.get("summarized_until", 1),
    )

    before_len = len(conversation.get_messages())

    with orchestrator.llm_client:
        orchestrator.process_user_input(user_message)

    messages = conversation.get_messages()
    store.save_messages(
        session_id,
        messages,
        summary=conversation.get_summary(),
        summarized_until=conversation.get_summarized_until(),
    )

    new_messages = messages[before_len:]

    return jsonify({
        "messages": new_messages,
        "session_id": session_id,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
