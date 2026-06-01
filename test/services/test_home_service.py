import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.home_service import HomeDataService


def _actor():
    return {"id": "u_001", "username": "alice", "role": "admin", "status": "active"}


def test_inventory_add_merge_update_and_audit(tmp_path):
    service = HomeDataService(tmp_path / "home", timezone_name="Asia/Shanghai")

    first = service.add_inventory_item(
        "fridge",
        {"name": "鸡蛋", "quantity": 6, "unit": "个", "expires_at": "2026-06-10"},
        _actor(),
    )
    second = service.add_inventory_item(
        "fridge",
        {"name": "土鸡蛋", "quantity": 2, "unit": "个", "expires_at": "2026-06-10"},
        _actor(),
    )
    updated = service.update_inventory_item(
        "fridge",
        first["item"]["id"],
        {"quantity": 4},
        _actor(),
    )

    fridge = service.list_inventory(location="fridge")
    assert len(fridge["items"]) == 1
    assert second["action"] == "inventory.merge"
    assert updated["item"]["quantity"] == 4
    assert len(service.activity_log()) == 3


def test_reminder_raw_time_receipt_and_dashboard_summary(tmp_path):
    service = HomeDataService(tmp_path / "home", timezone_name="Asia/Shanghai")

    result = service.create_reminder(
        {
            "title": "倒垃圾",
            "raw_text": "明天早上 8 点提醒我倒垃圾",
            "channels": ["in_app", "web_push"],
        },
        _actor(),
    )

    reminder = result["reminder"]
    assert reminder["trigger"]["run_at"].endswith("08:00:00+08:00")
    assert "任务 ID" in result["receipt"]
    summary = service.dashboard_task_summary()
    assert summary["kpis"]["total_tasks"] == 1
    assert summary["channel_distribution"]


def test_push_subscription_is_sanitized_and_test_falls_back(tmp_path):
    service = HomeDataService(tmp_path / "home", timezone_name="Asia/Shanghai")

    created = service.add_push_subscription(
        {
            "subscription": {
                "endpoint": "https://push.example/browser-token",
                "keys": {"p256dh": "secret-p256dh", "auth": "secret-auth"},
            },
            "device_name": "Mac Safari",
        },
        _actor(),
    )
    listed = service.list_push_subscriptions(_actor())
    test = service.send_test_push({"subscription_id": created["subscription"]["id"]}, _actor())

    assert "subscription" not in listed["subscriptions"][0]
    assert listed["subscriptions"][0]["endpoint_hash"].startswith("sha256:")
    assert test["web_push_configured"] is False
    assert test["notification"]["reason"] == "web_push_not_configured"
