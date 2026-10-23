"""Upload -> chat -> real SDK payload -> persisted conversation integration."""
from io import BytesIO
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from agent_runtime import RunStore
from services import ConversationStore
from services.llm_client import LLMClient
import web_app


@pytest.mark.parametrize("streaming", [False, True])
def test_uploaded_image_and_document_reach_model_and_survive_reload(tmp_path, monkeypatch, streaming):
    root = tmp_path / "files"
    uploads = root / "uploads"
    uploads.mkdir(parents=True)
    store = ConversationStore(tmp_path / "conversations")
    monkeypatch.setattr(web_app, "store", store)
    monkeypatch.setattr(web_app, "run_store", RunStore(tmp_path / "runs"))
    monkeypatch.setattr(web_app, "GENERATED_DIR", root)
    monkeypatch.setattr(web_app, "UPLOAD_DIR", uploads)
    monkeypatch.setitem(web_app.app.config, "TESTING", True)
    monkeypatch.setitem(web_app.config.config, "vision_model", "qwen3-vl-plus")
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        if kwargs.get("stream"):
            async def chunks():
                yield SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="识别完成", tool_calls=[]), finish_reason="stop",
                )])
            return chunks()
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="识别完成", tool_calls=[]), finish_reason="stop",
        )])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(LLMClient, "async_client", property(lambda self: fake_client))
    buffer = BytesIO()
    Image.new("RGB", (50, 50), "blue").save(buffer, format="PNG")

    with TestClient(web_app.app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        uploaded = client.post("/api/chat/uploads", files=[
            ("files", ("blue.png", buffer.getvalue(), "image/png")),
            ("files", ("notes.txt", "订单编号 ORDER-9421".encode(), "text/plain")),
        ])
        assert uploaded.status_code == 200
        media = uploaded.json()["media"]
        response = client.post("/api/chat/stream" if streaming else "/api/chat", json={
            "session_id": session_id,
            "message": "识别图片和文件",
            "images": [media[0]],
            "attachments": [media[1]],
        })
        assert response.status_code == 200
        if streaming:
            done = next(json.loads(line) for line in response.text.splitlines() if json.loads(line).get("type") == "done")
            assert done["run_status"] == "completed"
        else:
            assert response.json()["run_status"] == "completed"

        payload = calls[-1]
        assert payload["model"] == "qwen3-vl-plus"
        assert payload["tools"] and payload["tool_choice"] == "auto"
        content = next(message["content"] for message in payload["messages"] if message["role"] == "user")
        assert "ORDER-9421" in content[0]["text"]
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        saved = store.load_session(session_id)["messages"]
        user = next(message for message in saved if message["role"] == "user")
        assert user["images"][0]["url"] == media[0]["url"]
        assert "base64," not in json.dumps(saved)
        # A subsequent process can reconstruct the same model input from saved metadata.
        assert LLMClient._chat_messages([user], root)[0]["content"] == content


def test_vision_model_config_round_trip(tmp_path, monkeypatch):
    from config import ConfigManager
    for name in ("MODEL_NAME", "API_BASE_URL", "DASHSCOPE_API_KEY", "VISION_MODEL"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("DASHSCOPE_API_KEY=test-secret\nMODEL_NAME=qwen-plus\nVISION_MODEL=old-vision\n")
    config = ConfigManager(str(env))
    assert config["vision_model"] == "old-vision"
    public = config.update_llm_config(vision_model="custom-vision")
    assert public["vision_model"] == "custom-vision"
    assert "test-secret" not in str(public)
    assert "VISION_MODEL=custom-vision" in env.read_text()
    config.update_llm_config(vision_model="")
    assert config["vision_model"] == ""
