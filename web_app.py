#!/usr/bin/env python3
"""Web UI 入口"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, request

from config import ConfigManager
from core import AgentOrchestrator, ConversationManager
from services import LLMClient, CommandExecutor, ConversationStore
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
store = ConversationStore(conversation_root)
skills_dir = Path(config["skills_dir"])
if not skills_dir.is_absolute():
    skills_dir = PROJECT_ROOT / skills_dir
skill_registry = SkillRegistry(str(skills_dir))
executor = CommandExecutor(timeout=config["timeout"])


def _build_orchestrator() -> AgentOrchestrator:
    llm_client = LLMClient(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        timeout=config["timeout"],
    )
    conversation = ConversationManager(agent_prompt)
    return AgentOrchestrator(
        llm_client=llm_client,
        conversation=conversation,
        skill_registry=skill_registry,
        executor=executor,
    )


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/sessions")
def list_sessions():
    sessions = store.list_sessions()
    return jsonify([asdict(s) for s in sessions])


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

    before_len = len(conversation.get_messages())

    with orchestrator.llm_client:
        orchestrator.process_user_input(user_message)

    messages = conversation.get_messages()
    store.save_messages(session_id, messages)

    new_messages = messages[before_len:]

    return jsonify({
        "messages": new_messages,
        "session_id": session_id,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
