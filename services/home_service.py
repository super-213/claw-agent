"""File-backed home assistant data services."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo


HOME_LOCATIONS = {"fridge", "freezer", "pantry", "medicine"}
REMINDER_STATUSES = {"draft", "scheduled", "sent", "snoozed", "completed", "cancelled", "failed", "paused"}
CHANNELS = {"in_app", "web_push", "email", "webhook", "unread_center"}
WEEKDAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


class HomeDataService:
    """Manage home data under .data/home using readable JSON files."""

    def __init__(
        self,
        root_dir: str | Path,
        *,
        timezone_name: str = "Asia/Shanghai",
        quiet_start: str = "22:00",
        quiet_end: str = "07:00",
        log_retention_days: int = 15,
    ):
        self.root_dir = Path(root_dir)
        self.timezone_name = timezone_name or "Asia/Shanghai"
        self.timezone = ZoneInfo(self.timezone_name)
        self.quiet_start = quiet_start
        self.quiet_end = quiet_end
        self.log_retention_days = max(1, int(log_retention_days or 15))
        self._lock = Lock()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        (self.root_dir / "inventory").mkdir(parents=True, exist_ok=True)
        (self.root_dir / "backups").mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()
        self._prune_logs()

    def household(self) -> dict[str, Any]:
        return self._read_json(self._household_path(), self._default_household())

    def update_household(self, patch: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.household()
            settings = current.setdefault("settings", {})
            for key in ("name", "members"):
                if key in patch:
                    current[key] = patch[key]
            if isinstance(patch.get("settings"), dict):
                settings.update(patch["settings"])
            current["updated_at"] = self._now_iso()
            self._write_json(self._household_path(), current)
            self._activity("household.update", "household", None, actor, after=current)
            return current

    def activity_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._read_jsonl(self._activity_path())[-max(1, min(limit, 500)) :]

    def list_inventory(
        self,
        *,
        location: str | None = None,
        category: str | None = None,
        status: str | None = None,
        expires_before: str | None = None,
    ) -> dict[str, Any]:
        locations = [location] if location else sorted(HOME_LOCATIONS)
        result: dict[str, Any] = {"version": 1, "locations": {}}
        for loc in locations:
            self._validate_location(loc)
            data = self._inventory_doc(loc)
            items = data.get("items", [])
            if category:
                items = [item for item in items if item.get("category") == category]
            if status:
                items = [item for item in items if item.get("status") == status]
            if expires_before:
                cutoff = self._parse_date(expires_before)
                items = [
                    item for item in items
                    if item.get("expires_at") and self._parse_date(str(item["expires_at"])) <= cutoff
                ]
            result["locations"][loc] = {**data, "items": items}
        if location:
            return result["locations"][location]
        return result

    def expiring_items(self, *, days: int = 3, location: str | None = None) -> dict[str, Any]:
        today = self._now().date()
        cutoff = today + timedelta(days=max(0, days))
        rows = []
        inventory = self.list_inventory(location=location)
        docs = {location: inventory} if location else inventory.get("locations", {})
        for loc, doc in docs.items():
            for item in doc.get("items", []):
                expires_at = item.get("expires_at")
                if item.get("status") not in {"available", "low"} or not expires_at:
                    continue
                expiry = self._parse_date(str(expires_at))
                if today <= expiry <= cutoff:
                    rows.append({**item, "days_left": (expiry - today).days, "location": loc})
        rows.sort(key=lambda item: (item.get("expires_at") or "", item.get("name") or ""))
        return {"generated_at": self._now_iso(), "days": days, "items": rows}

    def add_inventory_item(self, location: str, payload: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        self._validate_location(location)
        with self._lock:
            doc = self._inventory_doc(location)
            now = self._now_iso()
            name = str(payload.get("name") or "").strip()
            if not name:
                raise ValueError("missing_name")
            normalized = self._normalize_name(payload.get("normalized_name") or name)
            expires_at = self._coerce_optional_date(payload.get("expires_at"))
            replace = bool(payload.get("replace"))
            matched = self._find_inventory_match(doc["items"], normalized, expires_at, location)
            before = deepcopy(matched) if matched else None
            if matched and not replace:
                matched["quantity"] = self._merge_quantity(matched.get("quantity"), payload.get("quantity"))
                for key in ("unit", "category", "zone", "status", "purchased_at", "opened_at", "confidence", "tags"):
                    if payload.get(key) not in (None, ""):
                        matched[key] = payload[key]
                matched["updated_by"] = actor.get("id")
                matched["updated_at"] = now
                item = matched
                action = "inventory.merge"
            elif matched and replace:
                matched.update(self._inventory_payload(location, payload, actor, now, existing_id=matched["id"]))
                item = matched
                action = "inventory.replace"
            else:
                item = self._inventory_payload(location, payload, actor, now)
                doc["items"].append(item)
                action = "inventory.add"
            doc["updated_at"] = now
            self._write_json(self._inventory_path(location), doc)
            self._activity(action, "inventory_item", item["id"], actor, before=before, after=item)
            return {"ok": True, "item": item, "action": action}

    def update_inventory_item(self, location: str, item_id: str, patch: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        self._validate_location(location)
        with self._lock:
            doc = self._inventory_doc(location)
            item = self._require_item(doc, item_id)
            before = deepcopy(item)
            for key in (
                "name", "normalized_name", "category", "zone", "quantity", "unit", "status",
                "expires_at", "purchased_at", "opened_at", "confidence", "tags",
            ):
                if key in patch:
                    item[key] = self._coerce_optional_date(patch[key]) if key.endswith("_at") else patch[key]
            if "name" in patch and "normalized_name" not in patch:
                item["normalized_name"] = self._normalize_name(str(patch["name"]))
            item["updated_by"] = actor.get("id")
            item["updated_at"] = self._now_iso()
            doc["updated_at"] = item["updated_at"]
            self._write_json(self._inventory_path(location), doc)
            self._activity("inventory.update", "inventory_item", item_id, actor, before=before, after=item)
            return {"ok": True, "item": item}

    def delete_inventory_item(self, location: str, item_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        self._validate_location(location)
        with self._lock:
            doc = self._inventory_doc(location)
            item = self._require_item(doc, item_id)
            doc["items"] = [candidate for candidate in doc["items"] if candidate.get("id") != item_id]
            doc["updated_at"] = self._now_iso()
            self._write_json(self._inventory_path(location), doc)
            self._activity("inventory.delete", "inventory_item", item_id, actor, before=item)
            return {"ok": True, "item": item}

    def consume_inventory_item(self, location: str, item_id: str, quantity: float | int | None, actor: dict[str, Any]) -> dict[str, Any]:
        self._validate_location(location)
        with self._lock:
            doc = self._inventory_doc(location)
            item = self._require_item(doc, item_id)
            before = deepcopy(item)
            if quantity is None or item.get("quantity") is None:
                item["quantity"] = 0
                item["status"] = "used_up"
            else:
                next_quantity = max(0, float(item.get("quantity") or 0) - float(quantity))
                item["quantity"] = int(next_quantity) if next_quantity.is_integer() else next_quantity
                item["status"] = "used_up" if next_quantity <= 0 else item.get("status") or "available"
            item["updated_by"] = actor.get("id")
            item["updated_at"] = self._now_iso()
            doc["updated_at"] = item["updated_at"]
            self._write_json(self._inventory_path(location), doc)
            self._activity("inventory.consume", "inventory_item", item_id, actor, before=before, after=item)
            return {"ok": True, "item": item}

    def restore_inventory_item(self, location: str, item_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        return self.update_inventory_item(location, item_id, {"status": "available"}, actor)

    def list_reminders(self, **filters: Any) -> dict[str, Any]:
        reminders = self._reminders_doc().get("reminders", [])
        if filters.get("status"):
            reminders = [item for item in reminders if item.get("status") == filters["status"]]
        if filters.get("recipient_user_id"):
            reminders = [item for item in reminders if filters["recipient_user_id"] in (item.get("recipients") or [])]
        if filters.get("channel"):
            reminders = [item for item in reminders if filters["channel"] in (item.get("channels") or [])]
        if filters.get("next_run_before"):
            cutoff = self._parse_datetime(str(filters["next_run_before"]))
            reminders = [
                item for item in reminders
                if item.get("next_run_at") and self._parse_datetime(str(item["next_run_at"])) <= cutoff
            ]
        if filters.get("type") == "one_time":
            reminders = [item for item in reminders if not (item.get("trigger") or {}).get("rrule")]
        if filters.get("type") == "recurring":
            reminders = [item for item in reminders if (item.get("trigger") or {}).get("rrule")]
        reminders.sort(key=lambda item: item.get("next_run_at") or item.get("created_at") or "")
        return {"version": 1, "updated_at": self._reminders_doc().get("updated_at"), "reminders": reminders}

    def create_reminder(self, payload: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            doc = self._reminders_doc()
            reminder = self._reminder_payload(payload, actor)
            doc["reminders"].append(reminder)
            doc["updated_at"] = self._now_iso()
            self._write_json(self._reminders_path(), doc)
            self._activity("reminder.add", "reminder", reminder["id"], actor, after=reminder)
            return {"ok": True, "reminder": reminder, "receipt": self.reminder_receipt("添加", reminder)}

    def get_reminder(self, reminder_id: str) -> dict[str, Any]:
        return self._require_reminder(self._reminders_doc(), reminder_id)

    def update_reminder(self, reminder_id: str, patch: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            doc = self._reminders_doc()
            reminder = self._require_reminder(doc, reminder_id)
            before = deepcopy(reminder)
            for key in ("title", "description", "recipients", "channels", "status", "priority", "quiet_hours_policy", "related_object"):
                if key in patch:
                    reminder[key] = patch[key]
            if "trigger" in patch or "run_at" in patch or "rrule" in patch or "raw_text" in patch:
                trigger_patch = patch.get("trigger") if isinstance(patch.get("trigger"), dict) else {}
                trigger_patch = {**trigger_patch}
                if "run_at" in patch:
                    trigger_patch["run_at"] = patch["run_at"]
                if "rrule" in patch:
                    trigger_patch["rrule"] = patch["rrule"]
                trigger_patch["raw_text"] = patch.get("raw_text") or trigger_patch.get("raw_text")
                reminder["trigger"] = self._normalize_trigger(trigger_patch, patch.get("raw_text"))
                reminder["next_run_at"] = self._next_run_for_trigger(reminder["trigger"])
            reminder["updated_at"] = self._now_iso()
            doc["updated_at"] = reminder["updated_at"]
            self._write_json(self._reminders_path(), doc)
            self._activity("reminder.update", "reminder", reminder_id, actor, before=before, after=reminder)
            return {"ok": True, "reminder": reminder, "receipt": self.reminder_receipt("更改", reminder, before=before)}

    def delete_reminder(self, reminder_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            doc = self._reminders_doc()
            reminder = self._require_reminder(doc, reminder_id)
            doc["reminders"] = [item for item in doc["reminders"] if item.get("id") != reminder_id]
            doc["updated_at"] = self._now_iso()
            self._write_json(self._reminders_path(), doc)
            self._activity("reminder.delete", "reminder", reminder_id, actor, before=reminder)
            return {"ok": True, "reminder": reminder, "receipt": self.reminder_receipt("删除", reminder, deleted=True)}

    def complete_reminder(self, reminder_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        return self.update_reminder(reminder_id, {"status": "completed"}, actor)

    def cancel_reminder(self, reminder_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        return self.update_reminder(reminder_id, {"status": "cancelled"}, actor)

    def snooze_reminder(self, reminder_id: str, minutes: int, actor: dict[str, Any]) -> dict[str, Any]:
        run_at = self._now() + timedelta(minutes=max(1, minutes))
        return self.update_reminder(reminder_id, {"status": "snoozed", "run_at": run_at.isoformat()}, actor)

    def list_schedules(self) -> dict[str, Any]:
        return self._schedules_doc()

    def create_schedule(self, payload: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            doc = self._schedules_doc()
            now = self._now_iso()
            schedule = {
                "id": payload.get("id") or self._new_id("sch"),
                "title": payload.get("title") or "周期任务",
                "description": payload.get("description") or "",
                "rrule": payload.get("rrule"),
                "next_run_at": payload.get("next_run_at") or now,
                "status": payload.get("status") or "scheduled",
                "created_by": actor.get("id"),
                "created_at": now,
                "updated_at": now,
            }
            doc["schedules"].append(schedule)
            doc["updated_at"] = now
            self._write_json(self._schedules_path(), doc)
            self._activity("schedule.add", "schedule", schedule["id"], actor, after=schedule)
            return {"ok": True, "schedule": schedule}

    def update_schedule(self, schedule_id: str, patch: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            doc = self._schedules_doc()
            schedule = self._require_by_id(doc.get("schedules", []), schedule_id, "schedule_not_found")
            before = deepcopy(schedule)
            for key in ("title", "description", "rrule", "next_run_at", "status"):
                if key in patch:
                    schedule[key] = patch[key]
            schedule["updated_at"] = self._now_iso()
            doc["updated_at"] = schedule["updated_at"]
            self._write_json(self._schedules_path(), doc)
            self._activity("schedule.update", "schedule", schedule_id, actor, before=before, after=schedule)
            return {"ok": True, "schedule": schedule}

    def delete_schedule(self, schedule_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            doc = self._schedules_doc()
            schedule = self._require_by_id(doc.get("schedules", []), schedule_id, "schedule_not_found")
            doc["schedules"] = [item for item in doc["schedules"] if item.get("id") != schedule_id]
            doc["updated_at"] = self._now_iso()
            self._write_json(self._schedules_path(), doc)
            self._activity("schedule.delete", "schedule", schedule_id, actor, before=schedule)
            return {"ok": True, "schedule": schedule}

    def notifications(self, *, unread_only: bool = False, limit: int = 100) -> dict[str, Any]:
        rows = self._read_jsonl(self._notification_path())
        if unread_only:
            rows = [row for row in rows if not row.get("read_at")]
        return {"notifications": rows[-max(1, min(limit, 500)) :][::-1]}

    def mark_notification_read(self, notification_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        rows = self._read_jsonl(self._notification_path())
        changed = False
        now = self._now_iso()
        for row in rows:
            if row.get("id") == notification_id:
                row["read_at"] = now
                row["read_by"] = actor.get("id")
                changed = True
                break
        if not changed:
            raise KeyError("notification_not_found")
        self._write_jsonl(self._notification_path(), rows)
        return {"ok": True}

    def mark_all_notifications_read(self, actor: dict[str, Any]) -> dict[str, Any]:
        rows = self._read_jsonl(self._notification_path())
        now = self._now_iso()
        for row in rows:
            if not row.get("read_at"):
                row["read_at"] = now
                row["read_by"] = actor.get("id")
        self._write_jsonl(self._notification_path(), rows)
        return {"ok": True, "count": len(rows)}

    def vapid_public_key(self) -> dict[str, Any]:
        public_key = os.environ.get("WEB_PUSH_VAPID_PUBLIC_KEY") or ""
        return {"public_key": public_key, "configured": bool(public_key and os.environ.get("WEB_PUSH_VAPID_PRIVATE_KEY"))}

    def list_push_subscriptions(self, user: dict[str, Any], *, include_all: bool = False) -> dict[str, Any]:
        subs = self._push_doc().get("subscriptions", [])
        if not include_all and user.get("role") != "admin":
            subs = [sub for sub in subs if sub.get("user_id") == user.get("id")]
        return {"subscriptions": [self._public_subscription(sub) for sub in subs]}

    def add_push_subscription(self, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
        subscription = payload.get("subscription")
        if not isinstance(subscription, dict) or not subscription.get("endpoint"):
            raise ValueError("invalid_subscription")
        endpoint_hash = self._endpoint_hash(str(subscription["endpoint"]))
        with self._lock:
            doc = self._push_doc()
            now = self._now_iso()
            existing = next((sub for sub in doc["subscriptions"] if sub.get("endpoint_hash") == endpoint_hash), None)
            if existing:
                existing.update({
                    "user_id": user.get("id"),
                    "subscription": subscription,
                    "user_agent": payload.get("user_agent") or existing.get("user_agent"),
                    "device_name": payload.get("device_name") or existing.get("device_name") or "浏览器",
                    "permission": payload.get("permission") or "granted",
                    "status": "active",
                    "last_seen_at": now,
                })
                sub = existing
            else:
                sub = {
                    "id": self._new_id("sub"),
                    "user_id": user.get("id"),
                    "endpoint_hash": endpoint_hash,
                    "subscription": subscription,
                    "user_agent": payload.get("user_agent") or "",
                    "device_name": payload.get("device_name") or "浏览器",
                    "permission": payload.get("permission") or "granted",
                    "status": "active",
                    "created_at": now,
                    "last_seen_at": now,
                    "last_success_at": None,
                    "last_failure_at": None,
                    "failure_count": 0,
                }
                doc["subscriptions"].append(sub)
            doc["updated_at"] = now
            self._write_json(self._push_path(), doc)
            return {"ok": True, "subscription": self._public_subscription(sub)}

    def update_push_subscription(self, subscription_id: str, patch: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            doc = self._push_doc()
            sub = self._require_subscription(doc, subscription_id, user)
            for key in ("device_name", "permission", "status"):
                if key in patch:
                    sub[key] = patch[key]
            sub["last_seen_at"] = self._now_iso()
            doc["updated_at"] = sub["last_seen_at"]
            self._write_json(self._push_path(), doc)
            return {"ok": True, "subscription": self._public_subscription(sub)}

    def delete_push_subscription(self, subscription_id: str, user: dict[str, Any]) -> dict[str, Any]:
        return self.update_push_subscription(subscription_id, {"status": "inactive"}, user)

    def send_test_push(self, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
        sub_id = payload.get("subscription_id")
        sub = None
        if sub_id:
            sub = self._require_subscription(self._push_doc(), str(sub_id), user)
        configured = self.vapid_public_key()["configured"]
        push_result = self._send_web_push(
            sub,
            {
                "title": payload.get("title") or "测试通知",
                "body": payload.get("body") or "家庭 Agent 推送已启用",
                "url": payload.get("url") or "/home",
                "tag": payload.get("tag") or "home-agent-test",
            },
        ) if configured and sub else {"sent": False, "reason": "web_push_not_configured" if not configured else "subscription_required"}
        if sub and configured:
            doc = self._push_doc()
            stored = next((item for item in doc.get("subscriptions", []) if item.get("id") == sub.get("id")), None)
            if stored:
                stored.update({
                    "status": sub.get("status"),
                    "last_success_at": sub.get("last_success_at"),
                    "last_failure_at": sub.get("last_failure_at"),
                    "failure_count": sub.get("failure_count") or 0,
                })
                doc["updated_at"] = self._now_iso()
                self._write_json(self._push_path(), doc)
        result = self._log_notification({
            "title": payload.get("title") or "测试通知",
            "body": payload.get("body") or "家庭 Agent 推送已启用",
            "url": payload.get("url") or "/home",
            "tag": payload.get("tag") or "home-agent-test",
            "recipients": [user.get("id")],
            "channels": ["web_push", "in_app"],
            "status": "sent" if push_result["sent"] else "fallback",
            "reason": None if push_result["sent"] else push_result["reason"],
            "subscription_id": sub.get("id") if sub else None,
        })
        return {"ok": True, "notification": result, "web_push_configured": configured, "web_push_sent": push_result["sent"]}

    def process_due_reminders(self) -> list[dict[str, Any]]:
        now = self._now()
        processed = []
        with self._lock:
            doc = self._reminders_doc()
            changed = False
            for reminder in doc.get("reminders", []):
                if reminder.get("status") not in {"scheduled", "snoozed"} or not reminder.get("next_run_at"):
                    continue
                if self._parse_datetime(str(reminder["next_run_at"])) > now:
                    continue
                notification = self._log_notification_for_reminder(reminder)
                before = deepcopy(reminder)
                rrule = (reminder.get("trigger") or {}).get("rrule")
                if rrule:
                    next_run = self._next_after_rrule(rrule, now + timedelta(seconds=1))
                    reminder["next_run_at"] = next_run.isoformat() if next_run else None
                    reminder["last_sent_at"] = now.isoformat()
                    reminder["status"] = "scheduled" if next_run else "completed"
                else:
                    reminder["last_sent_at"] = now.isoformat()
                    reminder["status"] = "sent"
                    reminder["next_run_at"] = None
                reminder["updated_at"] = now.isoformat()
                self._activity("reminder.sent", "reminder", reminder["id"], {"id": "system", "username": "system"}, before=before, after=reminder)
                processed.append({"reminder": reminder, "notification": notification})
                changed = True
            if changed:
                doc["updated_at"] = self._now_iso()
                self._write_json(self._reminders_path(), doc)
        return processed

    def dashboard_task_summary(self) -> dict[str, Any]:
        reminders = self._reminders_doc().get("reminders", [])
        notifications = self._read_jsonl(self._notification_path())
        now = self._now()
        today_end = datetime.combine(now.date(), time.max, tzinfo=self.timezone)
        week_end = now + timedelta(days=7)
        status_counts = Counter(item.get("status") or "unknown" for item in reminders)
        channel_counts = Counter(channel for item in reminders for channel in (item.get("channels") or []))
        recipient_counts = Counter(recipient for item in reminders for recipient in (item.get("recipients") or []))
        frequency_counts = Counter(self._frequency_label((item.get("trigger") or {}).get("rrule")) for item in reminders)
        failed_notifications = [row for row in notifications if row.get("status") in {"failed", "fallback"}]
        success_notifications = [row for row in notifications if row.get("status") in {"sent", "success", "queued"}]
        due_today = [item for item in reminders if self._due_between(item, now, today_end)]
        due_week = [item for item in reminders if self._due_between(item, now, week_end)]
        overdue = [
            item for item in reminders
            if item.get("status") == "scheduled"
            and item.get("next_run_at")
            and self._parse_datetime(str(item["next_run_at"])) < now
        ]
        return {
            "generated_at": self._now_iso(),
            "kpis": {
                "total_tasks": len(reminders),
                "one_time_tasks": sum(1 for item in reminders if not (item.get("trigger") or {}).get("rrule")),
                "recurring_tasks": sum(1 for item in reminders if (item.get("trigger") or {}).get("rrule")),
                "due_today": len(due_today),
                "due_next_7_days": len(due_week),
                "overdue": len(overdue),
                "failed_tasks": status_counts.get("failed", 0),
                "notification_success_rate": round(len(success_notifications) / max(1, len(notifications)) * 100, 2),
            },
            "status_distribution": self._counter_rows(status_counts),
            "channel_distribution": self._counter_rows(channel_counts),
            "recipient_distribution": self._counter_rows(recipient_counts),
            "frequency_distribution": self._counter_rows(frequency_counts),
            "notification_failures": self._counter_rows(Counter(row.get("reason") or "unknown" for row in failed_notifications)),
            "alerts": self._home_alerts(reminders, notifications, overdue),
        }

    def dashboard_task_timeseries(self, days: int = 30) -> dict[str, Any]:
        start = self._now().date() - timedelta(days=max(1, days) - 1)
        rows: dict[str, Counter] = {str(start + timedelta(days=i)): Counter() for i in range(max(1, days))}
        for entry in self._read_jsonl(self._activity_path()):
            action = str(entry.get("action") or "")
            if not action.startswith(("reminder.", "schedule.")):
                continue
            day = str(self._parse_datetime(str(entry.get("at") or self._now_iso())).date())
            if day in rows:
                rows[day][action.split(".", 1)[1]] += 1
        return {"timeseries": [{"date": day, **counts} for day, counts in rows.items()]}

    def dashboard_tasks(self, **filters: Any) -> dict[str, Any]:
        return self.list_reminders(**filters)

    def dashboard_notifications_summary(self) -> dict[str, Any]:
        rows = self._read_jsonl(self._notification_path())
        status_counts = Counter(row.get("status") or "unknown" for row in rows)
        reason_counts = Counter(row.get("reason") or "none" for row in rows if row.get("status") in {"failed", "fallback"})
        return {
            "generated_at": self._now_iso(),
            "total": len(rows),
            "status_distribution": self._counter_rows(status_counts),
            "failure_reasons": self._counter_rows(reason_counts),
            "recent": rows[-20:][::-1],
        }

    def handle_home_chat_intent(self, text: str, user: dict[str, Any], session_id: str | None = None) -> str | None:
        parsed = self._parse_inventory_text(text)
        if parsed:
            if parsed["intent"] == "query_expiring_items":
                rows = self.expiring_items(days=3, location="fridge")
                if not rows["items"]:
                    return f"根据 {rows['generated_at']} 的记录，未来 3 天冰箱里没有快过期物品。"
                lines = [f"根据 {rows['generated_at']} 的记录，未来 3 天快过期的物品："]
                for item in rows["items"]:
                    lines.append(f"- {item.get('name')}：{item.get('quantity') or '未知'}{item.get('unit') or ''}，{item.get('expires_at')} 到期")
                return "\n".join(lines)
            if parsed["intent"] == "query_inventory":
                doc = self.list_inventory(location="fridge")
                if not doc.get("items"):
                    return f"根据 {doc.get('updated_at')} 的记录，冰箱清单目前为空。"
                grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for item in doc.get("items", []):
                    if item.get("status") in {"available", "low"}:
                        grouped[item.get("category") or "其他"].append(item)
                lines = [f"根据 {doc.get('updated_at')} 的记录，冰箱里有："]
                for category, items in grouped.items():
                    names = "、".join(f"{item.get('name')} {item.get('quantity') or '未知'}{item.get('unit') or ''}" for item in items)
                    lines.append(f"- {category}：{names}")
                return "\n".join(lines)
            if parsed["intent"] == "update_inventory_quantity":
                match = self._first_inventory_by_name("fridge", parsed["name"])
                if match:
                    result = self.update_inventory_item("fridge", match["id"], {"quantity": parsed["quantity"], "unit": parsed["unit"]}, user)
                else:
                    result = self.add_inventory_item("fridge", parsed, user)
                item = result["item"]
                return f"已更新冰箱清单：{item['name']} 现在是 {item.get('quantity')}{item.get('unit') or ''}。"
            if parsed["intent"] == "add_inventory_item":
                payload = {**parsed, "source": {"type": "chat", "session_id": session_id}}
                result = self.add_inventory_item("fridge", payload, user)
                item = result["item"]
                expiry = f"，{item['expires_at']} 到期" if item.get("expires_at") else ""
                return f"已记下：冰箱{item.get('zone') or ''}有 {item['quantity'] if item.get('quantity') is not None else '未知'}{item.get('unit') or ''}{item['name']}{expiry}。"
        reminder = self._parse_reminder_text(text, user)
        if reminder:
            result = self.create_reminder(reminder, user)
            return result["receipt"]
        mismatch = self._parse_inventory_usage_mismatch(text)
        if mismatch:
            item = self._first_inventory_by_name("fridge", mismatch["name"])
            if item and item.get("quantity") is not None and float(mismatch["quantity"]) > float(item.get("quantity") or 0):
                return (
                    f"我这里记录冰箱里现在只有 {item.get('quantity')}{item.get('unit') or ''}{item.get('name')}，不是 "
                    f"{mismatch['quantity']}{mismatch['unit']}。\n"
                    "你是记错数量了，还是冰箱里实际已经变化、需要我更新库存？如果按当前记录，我也可以先按现有数量继续建议。"
                )
        return None

    def reminder_receipt(
        self,
        operation: str,
        reminder: dict[str, Any],
        *,
        before: dict[str, Any] | None = None,
        deleted: bool = False,
    ) -> str:
        trigger = reminder.get("trigger") or {}
        rrule = trigger.get("rrule")
        lines = [f"已{operation}提醒任务：{reminder.get('title') or reminder.get('id')}"]
        if before:
            lines.append(f"- 原时间：{before.get('next_run_at') or (before.get('trigger') or {}).get('run_at') or '未设置'}")
            lines.append(f"- 新时间：{reminder.get('next_run_at') or trigger.get('run_at') or '未设置'}")
        else:
            lines.append(f"- 时间：{reminder.get('next_run_at') or trigger.get('run_at') or '未设置'}")
        lines.extend([
            f"- 任务 ID：{reminder.get('id')}",
            f"- 事件：{reminder.get('description') or reminder.get('title') or ''}",
            f"- 频率：{self._frequency_label(rrule)}",
            f"- 重复规则：{rrule or '不重复'}",
            f"- 提醒对象：{', '.join(reminder.get('recipients') or []) or '你'}",
            f"- 提醒渠道：{', '.join(reminder.get('channels') or []) or 'in_app'}",
            f"- 提醒内容：{reminder.get('description') or reminder.get('title') or ''}",
            f"- 状态：{'已删除' if deleted else reminder.get('status')}",
            f"- 免打扰策略：{reminder.get('quiet_hours_policy') or 'delay'}",
        ])
        return "\n".join(lines)

    def _ensure_defaults(self) -> None:
        defaults = {
            self._household_path(): self._default_household(),
            self._reminders_path(): {"version": 1, "updated_at": self._now_iso(), "reminders": []},
            self._schedules_path(): {"version": 1, "updated_at": self._now_iso(), "schedules": []},
            self._push_path(): {"version": 1, "updated_at": self._now_iso(), "subscriptions": []},
        }
        for path, payload in defaults.items():
            if not path.exists():
                self._write_json(path, payload)
        for loc in HOME_LOCATIONS:
            path = self._inventory_path(loc)
            if not path.exists():
                self._write_json(path, {"version": 1, "updated_at": self._now_iso(), "items": []})
        self._notification_path().touch(exist_ok=True)
        self._activity_path().touch(exist_ok=True)

    def _default_household(self) -> dict[str, Any]:
        return {
            "version": 1,
            "name": "家庭",
            "members": [],
            "settings": {
                "timezone": self.timezone_name,
                "quiet_hours": {"start": self.quiet_start, "end": self.quiet_end},
                "default_channels": ["in_app", "web_push"],
            },
            "updated_at": self._now_iso(),
        }

    def _household_path(self) -> Path:
        return self.root_dir / "household.json"

    def _inventory_path(self, location: str) -> Path:
        return self.root_dir / "inventory" / f"{location}.json"

    def _reminders_path(self) -> Path:
        return self.root_dir / "reminders.json"

    def _schedules_path(self) -> Path:
        return self.root_dir / "schedules.json"

    def _push_path(self) -> Path:
        return self.root_dir / "push_subscriptions.json"

    def _notification_path(self) -> Path:
        return self.root_dir / "notification_log.jsonl"

    def _activity_path(self) -> Path:
        return self.root_dir / "activity_log.jsonl"

    def _inventory_doc(self, location: str) -> dict[str, Any]:
        return self._read_json(self._inventory_path(location), {"version": 1, "updated_at": self._now_iso(), "items": []})

    def _reminders_doc(self) -> dict[str, Any]:
        doc = self._read_json(self._reminders_path(), {"version": 1, "updated_at": self._now_iso(), "reminders": []})
        doc.setdefault("reminders", [])
        return doc

    def _schedules_doc(self) -> dict[str, Any]:
        doc = self._read_json(self._schedules_path(), {"version": 1, "updated_at": self._now_iso(), "schedules": []})
        doc.setdefault("schedules", [])
        return doc

    def _push_doc(self) -> dict[str, Any]:
        doc = self._read_json(self._push_path(), {"version": 1, "updated_at": self._now_iso(), "subscriptions": []})
        doc.setdefault("subscriptions", [])
        return doc

    def _read_json(self, path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            backup = path.with_suffix(path.suffix + ".corrupt")
            try:
                path.replace(backup)
            except OSError:
                pass
        return deepcopy(fallback)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
        os.replace(tmp, path)

    def _append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        rows = self._read_jsonl(path)
        rows.append(row)
        rows = self._retained_log_rows(path, rows)
        self._write_jsonl(path, rows)

    def _prune_logs(self) -> None:
        for path in (self._activity_path(), self._notification_path()):
            rows = self._read_jsonl(path)
            retained = self._retained_log_rows(path, rows)
            if len(retained) != len(rows):
                self._write_jsonl(path, retained)

    def _retained_log_rows(self, path: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if path == self._activity_path():
            return self._filter_rows_by_age(rows, "at")
        if path == self._notification_path():
            return self._filter_rows_by_age(rows, "created_at")
        return rows

    def _filter_rows_by_age(self, rows: list[dict[str, Any]], timestamp_key: str) -> list[dict[str, Any]]:
        cutoff = self._now() - timedelta(days=self.log_retention_days)
        retained = []
        for row in rows:
            timestamp = row.get(timestamp_key)
            if not timestamp:
                retained.append(row)
                continue
            try:
                parsed = self._parse_datetime(str(timestamp))
            except (TypeError, ValueError):
                retained.append(row)
                continue
            if parsed >= cutoff:
                retained.append(row)
        return retained

    def _activity(
        self,
        action: str,
        object_type: str,
        object_id: str | None,
        actor: dict[str, Any],
        *,
        before: Any = None,
        after: Any = None,
    ) -> None:
        self._append_jsonl(self._activity_path(), {
            "id": self._new_id("act"),
            "at": self._now_iso(),
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "actor_id": actor.get("id"),
            "actor_name": actor.get("username") or actor.get("display_name"),
            "before": before,
            "after": after,
        })

    def _log_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            "id": payload.get("id") or self._new_id("noti"),
            "created_at": self._now_iso(),
            "title": payload.get("title") or "家庭提醒",
            "body": payload.get("body") or "",
            "url": payload.get("url") or "/home",
            "tag": payload.get("tag") or payload.get("id"),
            "recipients": payload.get("recipients") or [],
            "channels": payload.get("channels") or ["in_app"],
            "status": payload.get("status") or "queued",
            "reason": payload.get("reason"),
            "subscription_id": payload.get("subscription_id"),
            "read_at": None,
        }
        self._append_jsonl(self._notification_path(), row)
        return row

    def _log_notification_for_reminder(self, reminder: dict[str, Any]) -> dict[str, Any]:
        notification = {
            "title": reminder.get("title") or "家庭提醒",
            "body": reminder.get("description") or reminder.get("title") or "",
            "url": f"/home/reminders/{reminder.get('id')}",
            "tag": reminder.get("id"),
            "recipients": reminder.get("recipients") or [],
            "channels": reminder.get("channels") or ["in_app"],
            "status": "queued",
            "reason": None,
        }
        if "web_push" in notification["channels"]:
            push_result = self._send_web_push_to_recipients(notification["recipients"], notification)
            if push_result["attempted"]:
                notification["status"] = "sent" if push_result["sent"] else "failed"
                notification["reason"] = None if push_result["sent"] else push_result["reason"]
            elif self.vapid_public_key()["configured"]:
                notification["status"] = "fallback"
                notification["reason"] = "no_active_subscription"
            else:
                notification["status"] = "fallback"
                notification["reason"] = "web_push_not_configured"
        return self._log_notification(notification)

    def _send_web_push_to_recipients(self, recipients: list[str], notification: dict[str, Any]) -> dict[str, Any]:
        doc = self._push_doc()
        subs = [
            sub for sub in doc.get("subscriptions", [])
            if sub.get("status") == "active" and sub.get("user_id") in set(recipients)
        ]
        sent = 0
        reason = "no_active_subscription"
        changed = False
        for sub in subs:
            result = self._send_web_push(sub, notification)
            changed = True
            if result["sent"]:
                sent += 1
            else:
                reason = result["reason"]
        if changed:
            doc["updated_at"] = self._now_iso()
            self._write_json(self._push_path(), doc)
        return {"attempted": len(subs), "sent": sent, "reason": reason}

    def _send_web_push(self, sub: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
        if not sub:
            return {"sent": False, "reason": "subscription_required"}
        private_key = os.environ.get("WEB_PUSH_VAPID_PRIVATE_KEY")
        subject = os.environ.get("WEB_PUSH_SUBJECT") or "mailto:admin@example.com"
        if not private_key:
            return {"sent": False, "reason": "web_push_not_configured"}
        try:
            from pywebpush import WebPushException, webpush
        except Exception:
            return {"sent": False, "reason": "pywebpush_missing"}
        try:
            webpush(
                subscription_info=sub.get("subscription") or {},
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
            )
            sub["last_success_at"] = self._now_iso()
            sub["last_failure_at"] = None
            sub["failure_count"] = 0
            return {"sent": True, "reason": None}
        except WebPushException as exc:
            sub["last_failure_at"] = self._now_iso()
            sub["failure_count"] = int(sub.get("failure_count") or 0) + 1
            if getattr(exc, "response", None) is not None and exc.response.status_code in {404, 410}:
                sub["status"] = "expired"
                return {"sent": False, "reason": "subscription_expired"}
            return {"sent": False, "reason": "web_push_failed"}
        except Exception:
            sub["last_failure_at"] = self._now_iso()
            sub["failure_count"] = int(sub.get("failure_count") or 0) + 1
            return {"sent": False, "reason": "web_push_failed"}

    def _inventory_payload(
        self,
        location: str,
        payload: dict[str, Any],
        actor: dict[str, Any],
        now: str,
        *,
        existing_id: str | None = None,
    ) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        normalized = self._normalize_name(payload.get("normalized_name") or name)
        return {
            "id": existing_id or self._new_id("inv"),
            "name": name,
            "normalized_name": normalized,
            "category": payload.get("category") or self._guess_category(name),
            "location": location,
            "zone": payload.get("zone") or ("冷冻层" if location == "freezer" else "冷藏层" if location == "fridge" else ""),
            "quantity": self._coerce_quantity(payload.get("quantity")),
            "unit": payload.get("unit") or "",
            "status": payload.get("status") or "available",
            "expires_at": self._coerce_optional_date(payload.get("expires_at")),
            "purchased_at": self._coerce_optional_date(payload.get("purchased_at")),
            "opened_at": self._coerce_optional_date(payload.get("opened_at")),
            "source": payload.get("source") or {"type": "ui"},
            "confidence": payload.get("confidence", 1.0),
            "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
            "created_by": actor.get("id"),
            "updated_by": actor.get("id"),
            "created_at": payload.get("created_at") or now,
            "updated_at": now,
        }

    def _reminder_payload(self, payload: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        now = self._now_iso()
        trigger = self._normalize_trigger(payload.get("trigger") if isinstance(payload.get("trigger"), dict) else payload, payload.get("raw_text"))
        channels = payload.get("channels") or self.household().get("settings", {}).get("default_channels") or ["in_app"]
        channels = [channel for channel in channels if channel in CHANNELS] or ["in_app"]
        recipients = payload.get("recipients") or [actor.get("id")]
        status = payload.get("status") or "scheduled"
        if status not in REMINDER_STATUSES:
            status = "scheduled"
        return {
            "id": payload.get("id") or self._new_id("rem"),
            "title": payload.get("title") or "家庭提醒",
            "description": payload.get("description") or payload.get("title") or "",
            "timezone": payload.get("timezone") or self.timezone_name,
            "trigger": trigger,
            "recipients": recipients,
            "channels": channels,
            "status": status,
            "priority": payload.get("priority") or "normal",
            "quiet_hours_policy": payload.get("quiet_hours_policy") or "delay",
            "related_object": payload.get("related_object"),
            "created_by": actor.get("id"),
            "created_at": now,
            "updated_at": now,
            "last_sent_at": None,
            "next_run_at": payload.get("next_run_at") or self._next_run_for_trigger(trigger),
            "created_from": payload.get("created_from") or "ui",
        }

    def _normalize_trigger(self, payload: dict[str, Any], raw_text: str | None = None) -> dict[str, Any]:
        raw = raw_text or payload.get("raw_text")
        run_at = payload.get("run_at")
        rrule = payload.get("rrule")
        if not run_at and raw:
            parsed = self._resolve_raw_time(str(raw))
            run_at = parsed.get("run_at")
            rrule = rrule or parsed.get("rrule")
        if rrule and not run_at:
            run_at_dt = self._next_after_rrule(str(rrule), self._now())
            run_at = run_at_dt.isoformat() if run_at_dt else None
        if run_at:
            run_at = self._parse_datetime(str(run_at)).isoformat()
        return {
            "type": "datetime",
            "raw_text": raw,
            "resolved_at": self._now_iso(),
            "run_at": run_at,
            "rrule": rrule,
        }

    def _next_run_for_trigger(self, trigger: dict[str, Any]) -> str | None:
        rrule = trigger.get("rrule")
        if rrule:
            next_run = self._next_after_rrule(str(rrule), self._now())
            return next_run.isoformat() if next_run else None
        return trigger.get("run_at")

    def _resolve_raw_time(self, text: str) -> dict[str, Any]:
        now = self._now()
        hour = 8
        minute = 0
        hm = re.search(r"(\d{1,2})\s*[点:：](?:\s*(\d{1,2})\s*分?)?", text)
        if hm:
            hour = int(hm.group(1))
            minute = int(hm.group(2) or 0)
        elif "晚上" in text:
            hour = 21
        elif "早上" in text or "上午" in text:
            hour = 8
        if "半小时后" in text:
            return {"run_at": (now + timedelta(minutes=30)).isoformat()}
        rel = re.search(r"(\d+)\s*分钟后", text)
        if rel:
            return {"run_at": (now + timedelta(minutes=int(rel.group(1)))).isoformat()}
        weekday = self._parse_weekday(text)
        if "每周" in text and weekday is not None:
            rrule = f"FREQ=WEEKLY;BYDAY={self._weekday_code(weekday)};BYHOUR={hour};BYMINUTE={minute}"
            return {"rrule": rrule, "run_at": self._next_after_rrule(rrule, now).isoformat()}
        month_day = re.search(r"每月\s*(\d{1,2})\s*号?", text)
        if month_day:
            rrule = f"FREQ=MONTHLY;BYMONTHDAY={int(month_day.group(1))};BYHOUR={hour};BYMINUTE={minute}"
            return {"rrule": rrule, "run_at": self._next_after_rrule(rrule, now).isoformat()}
        if "每天" in text or "每日" in text:
            rrule = f"FREQ=DAILY;BYHOUR={hour};BYMINUTE={minute}"
            return {"rrule": rrule, "run_at": self._next_after_rrule(rrule, now).isoformat()}
        target_date = now.date()
        if "后天" in text:
            target_date += timedelta(days=2)
        elif "明天" in text:
            target_date += timedelta(days=1)
        else:
            absolute = re.search(r"(?:(\d{4})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", text)
            if absolute:
                year = int(absolute.group(1) or now.year)
                target_date = date(year, int(absolute.group(2)), int(absolute.group(3)))
        return {"run_at": datetime.combine(target_date, time(hour, minute), tzinfo=self.timezone).isoformat()}

    def _next_after_rrule(self, rrule: str, after: datetime) -> datetime | None:
        parts = dict(part.split("=", 1) for part in rrule.split(";") if "=" in part)
        freq = parts.get("FREQ")
        hour = int(parts.get("BYHOUR", "8"))
        minute = int(parts.get("BYMINUTE", "0"))
        current = after.astimezone(self.timezone)
        for offset in range(0, 400):
            day = current.date() + timedelta(days=offset)
            candidate = datetime.combine(day, time(hour, minute), tzinfo=self.timezone)
            if candidate <= current:
                continue
            if freq == "DAILY":
                return candidate
            if freq == "WEEKLY":
                days = [WEEKDAY_CODES.get(code) for code in parts.get("BYDAY", "").split(",") if code in WEEKDAY_CODES]
                if candidate.weekday() in days:
                    return candidate
            if freq == "MONTHLY":
                month_day = int(parts.get("BYMONTHDAY", "1"))
                if candidate.day == month_day:
                    return candidate
        return None

    def _parse_inventory_text(self, text: str) -> dict[str, Any] | None:
        if "冰箱" in text and ("快过期" in text or "要过期" in text):
            return {"intent": "query_expiring_items"}
        if "冰箱" in text and any(word in text for word in ("有什么", "还有什么", "清单")):
            return {"intent": "query_inventory"}
        add = re.search(r"(?:记一下|刚买了|买了|放进).*?冰箱(?P<zone>冷藏层|冷冻层|门架|抽屉)?(?:里|中|有)?\s*(?P<qty>\d+(?:\.\d+)?)?\s*(?P<unit>kg|g|斤|个|盒|瓶|根|片|袋)?\s*(?P<name>[\u4e00-\u9fa5A-Za-z]+)", text)
        if add:
            name = add.group("name")
            name = re.sub(r"(过期|到期|提醒|放入|放进)$", "", name)
            return {
                "intent": "add_inventory_item",
                "name": name,
                "quantity": self._coerce_quantity(add.group("qty")),
                "unit": add.group("unit") or "",
                "zone": add.group("zone") or "冷藏层",
                "expires_at": self._extract_expiry(text),
                "category": self._guess_category(name),
                "created_from": "chat",
            }
        update = re.search(r"(?P<name>[\u4e00-\u9fa5A-Za-z]+)(?:还剩|剩|现在有)\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|斤|个|盒|瓶|根|片|袋)?", text)
        if update:
            return {
                "intent": "update_inventory_quantity",
                "name": update.group("name"),
                "quantity": self._coerce_quantity(update.group("qty")),
                "unit": update.group("unit") or "",
            }
        return None

    def _parse_inventory_usage_mismatch(self, text: str) -> dict[str, Any] | None:
        match = re.search(r"冰箱里的?\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>个|盒|瓶|根|片|袋|kg|g|斤)?\s*(?P<name>[\u4e00-\u9fa5A-Za-z]+)", text)
        if not match:
            return None
        return {"quantity": self._coerce_quantity(match.group("qty")), "unit": match.group("unit") or "", "name": match.group("name")}

    def _parse_reminder_text(self, text: str, user: dict[str, Any]) -> dict[str, Any] | None:
        if "提醒" not in text:
            return None
        title_match = re.search(r"提醒我(?P<title>.+?)(?:。|$)", text)
        title = (title_match.group("title") if title_match else text).strip(" ，。.")
        title = re.sub(r"^(带|去|给|把)?", "", title).strip() or "家庭提醒"
        if "每周" in text or "每月" in text or "每天" in text or "明天" in text or "后天" in text or "分钟后" in text or "半小时后" in text or re.search(r"\d+\s*[点:：]", text):
            return {
                "title": title[:40],
                "description": f"提醒你{title}",
                "raw_text": text,
                "recipients": [user.get("id")],
                "channels": ["in_app", "web_push"],
                "created_from": "chat",
            }
        return None

    def _extract_expiry(self, text: str) -> str | None:
        today = self._now().date()
        if "明天过期" in text or "明天到期" in text:
            return str(today + timedelta(days=1))
        match = re.search(r"(?:(\d{4})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?(?:过期|到期)?", text)
        if match:
            return str(date(int(match.group(1) or today.year), int(match.group(2)), int(match.group(3))))
        return None

    def _first_inventory_by_name(self, location: str, name: str) -> dict[str, Any] | None:
        normalized = self._normalize_name(name)
        for item in self._inventory_doc(location).get("items", []):
            if item.get("normalized_name") == normalized and item.get("status") != "discarded":
                return item
        return None

    def _find_inventory_match(self, items: list[dict[str, Any]], normalized: str, expires_at: str | None, location: str) -> dict[str, Any] | None:
        for item in items:
            if item.get("normalized_name") == normalized and item.get("location") == location and item.get("expires_at") == expires_at:
                return item
        return None

    def _require_item(self, doc: dict[str, Any], item_id: str) -> dict[str, Any]:
        return self._require_by_id(doc.get("items", []), item_id, "item_not_found")

    def _require_reminder(self, doc: dict[str, Any], reminder_id: str) -> dict[str, Any]:
        return self._require_by_id(doc.get("reminders", []), reminder_id, "reminder_not_found")

    def _require_by_id(self, rows: list[dict[str, Any]], item_id: str, error: str) -> dict[str, Any]:
        item = next((row for row in rows if row.get("id") == item_id), None)
        if item is None:
            raise KeyError(error)
        return item

    def _require_subscription(self, doc: dict[str, Any], subscription_id: str, user: dict[str, Any]) -> dict[str, Any]:
        sub = self._require_by_id(doc.get("subscriptions", []), subscription_id, "subscription_not_found")
        if user.get("role") != "admin" and sub.get("user_id") != user.get("id"):
            raise PermissionError("forbidden")
        return sub

    def _public_subscription(self, sub: dict[str, Any]) -> dict[str, Any]:
        endpoint_hash = sub.get("endpoint_hash") or ""
        return {
            "id": sub.get("id"),
            "user_id": sub.get("user_id"),
            "endpoint_hash": endpoint_hash[:18] + "..." if len(endpoint_hash) > 18 else endpoint_hash,
            "device_name": sub.get("device_name"),
            "user_agent": sub.get("user_agent"),
            "permission": sub.get("permission"),
            "status": sub.get("status"),
            "created_at": sub.get("created_at"),
            "last_seen_at": sub.get("last_seen_at"),
            "last_success_at": sub.get("last_success_at"),
            "last_failure_at": sub.get("last_failure_at"),
            "failure_count": sub.get("failure_count") or 0,
        }

    def _due_between(self, reminder: dict[str, Any], start: datetime, end: datetime) -> bool:
        if reminder.get("status") not in {"scheduled", "snoozed"} or not reminder.get("next_run_at"):
            return False
        run_at = self._parse_datetime(str(reminder["next_run_at"]))
        return start <= run_at <= end

    def _home_alerts(self, reminders: list[dict[str, Any]], notifications: list[dict[str, Any]], overdue: list[dict[str, Any]]) -> list[dict[str, Any]]:
        alerts = []
        for item in overdue[:5]:
            alerts.append({"level": "warn", "title": "逾期未发送任务", "message": item.get("title"), "id": item.get("id")})
        for item in reminders:
            if item.get("status") == "failed":
                alerts.append({"level": "danger", "title": "失败任务", "message": item.get("title"), "id": item.get("id")})
        for row in notifications[-20:]:
            if row.get("reason") == "web_push_not_configured":
                alerts.append({"level": "info", "title": "Web Push 未配置", "message": "测试或提醒已进入站内通知", "id": row.get("id")})
                break
        return alerts[:10]

    @staticmethod
    def _counter_rows(counter: Counter) -> list[dict[str, Any]]:
        return [{"label": key, "value": value} for key, value in counter.most_common()]

    @staticmethod
    def _frequency_label(rrule: str | None) -> str:
        if not rrule:
            return "一次性"
        if "FREQ=DAILY" in rrule:
            return "每天"
        if "FREQ=WEEKLY" in rrule:
            return "每周"
        if "FREQ=MONTHLY" in rrule:
            return "每月"
        return "自定义"

    @staticmethod
    def _normalize_name(value: str) -> str:
        value = str(value or "").strip().lower()
        aliases = {"蛋": "鸡蛋", "土鸡蛋": "鸡蛋", "牛奶": "牛奶", "奶": "牛奶"}
        return aliases.get(value, value)

    @staticmethod
    def _guess_category(name: str) -> str:
        if any(word in name for word in ("蛋", "奶", "酸奶", " cheese", "芝士")):
            return "蛋奶"
        if any(word in name for word in ("牛", "猪", "鸡", "鱼", "肉", "虾")):
            return "肉类"
        if any(word in name for word in ("黄瓜", "青菜", "白菜", "番茄", "西红柿", "菜")):
            return "蔬菜"
        if any(word in name for word in ("苹果", "香蕉", "橙", "梨")):
            return "水果"
        if any(word in name for word in ("药", "片", "胶囊")):
            return "药品"
        return "其他"

    @staticmethod
    def _merge_quantity(existing: Any, incoming: Any) -> Any:
        if incoming is None:
            return existing
        if existing is None:
            return HomeDataService._coerce_quantity(incoming)
        merged = float(existing) + float(incoming)
        return int(merged) if merged.is_integer() else merged

    @staticmethod
    def _coerce_quantity(value: Any) -> float | int | None:
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number

    def _coerce_optional_date(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(self._parse_date(str(value)))

    def _parse_date(self, value: str) -> date:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if "T" in value else date.fromisoformat(value)

    def _parse_datetime(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self.timezone)
        return parsed.astimezone(self.timezone)

    def _parse_weekday(self, text: str) -> int | None:
        mapping = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        match = re.search(r"周([一二三四五六日天])|星期([一二三四五六日天])", text)
        if not match:
            return None
        return mapping[match.group(1) or match.group(2)]

    @staticmethod
    def _weekday_code(index: int) -> str:
        return ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][index]

    def _validate_location(self, location: str) -> None:
        if location not in HOME_LOCATIONS:
            raise ValueError("invalid_location")

    @staticmethod
    def _endpoint_hash(endpoint: str) -> str:
        return "sha256:" + hashlib.sha256(endpoint.encode("utf-8")).hexdigest()

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _now(self) -> datetime:
        return datetime.now(self.timezone)

    def _now_iso(self) -> str:
        return self._now().isoformat()
