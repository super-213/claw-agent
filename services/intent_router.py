"""Hybrid intent routing for chat requests.

Rules handle deterministic, high-confidence cases first. The intent LLM is a
fallback that only returns structured JSON; local services still validate and
execute every action.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable, Literal

from skills.registry import SkillRegistry
from utils.parser import InputParser

from .home_assistant_service import HomeAssistantService
from .home_service import HomeDataService
from .llm_client import LLMClient


IntentAction = Literal["direct_response", "load_skills", "general_chat"]


@dataclass
class IntentRouteResult:
    action: IntentAction
    source: str
    stage: str = "intent"
    confidence: float = 0.0
    reply: str | None = None
    skills: list[str] = field(default_factory=list)
    model_response: dict[str, Any] | None = None


class HybridIntentRouter:
    """Resolve user text to a local action, skill context, or normal chat."""

    SAFE_SKILL_MIN_CONFIDENCE = 0.55
    ACTION_MIN_CONFIDENCE = 0.70

    def __init__(
        self,
        *,
        llm_factory: Callable[[], LLMClient],
        home_assistant_service: HomeAssistantService,
        home_service: HomeDataService,
        skill_registry: SkillRegistry,
    ):
        self.llm_factory = llm_factory
        self.home_assistant_service = home_assistant_service
        self.home_service = home_service
        self.skill_registry = skill_registry

    async def route(
        self,
        text: str,
        user: dict[str, Any],
        session_id: str | None = None,
    ) -> IntentRouteResult:
        normalized = (text or "").strip()
        if not normalized:
            return IntentRouteResult(action="general_chat", source="empty")

        rule_result = await self._route_by_rules(normalized, user, session_id)
        if rule_result.action != "general_chat":
            return rule_result

        llm_result = await self._route_by_llm(normalized, user, session_id)
        return llm_result or IntentRouteResult(action="general_chat", source="llm_no_match")

    async def _route_by_rules(
        self,
        text: str,
        user: dict[str, Any],
        session_id: str | None,
    ) -> IntentRouteResult:
        skill_name, _cleaned = InputParser.parse_user_input(text)
        if skill_name and self.skill_registry.has_skill(skill_name):
            return IntentRouteResult(
                action="load_skills",
                source="rule:explicit_skill",
                stage="skill",
                confidence=1.0,
                skills=[skill_name],
            )

        ha_reply = await asyncio.to_thread(
            self.home_assistant_service.handle_chat_intent,
            text,
            user,
            session_id,
        )
        if ha_reply:
            return IntentRouteResult(
                action="direct_response",
                source="rule:home_assistant",
                stage="home_assistant",
                confidence=1.0,
                reply=ha_reply,
            )

        home_reply = await asyncio.to_thread(
            self.home_service.handle_home_chat_intent,
            text,
            user,
            session_id,
        )
        if home_reply:
            return IntentRouteResult(
                action="direct_response",
                source="rule:home",
                stage="home",
                confidence=1.0,
                reply=home_reply,
            )

        skills: list[str] = []
        if InputParser.needs_realtime_search(text) and self.skill_registry.has_skill("search"):
            skills.append("search")
        if self._looks_like_calculation(text) and self.skill_registry.has_skill("calculator"):
            skills.append("calculator")

        if skills:
            return IntentRouteResult(
                action="load_skills",
                source="rule:auto_skill",
                stage="skill",
                confidence=0.9,
                skills=skills,
            )

        return IntentRouteResult(action="general_chat", source="rule:no_match")

    async def _route_by_llm(
        self,
        text: str,
        user: dict[str, Any],
        session_id: str | None,
    ) -> IntentRouteResult | None:
        llm_payload = await self._detect_with_llm(text)
        if not llm_payload:
            return None

        confidence = self._coerce_confidence(llm_payload.get("confidence"))
        domain = str(llm_payload.get("domain") or "general").strip()
        intent = str(llm_payload.get("intent") or "unknown").strip()
        slots = llm_payload.get("slots") if isinstance(llm_payload.get("slots"), dict) else {}

        if domain == "skill" and confidence >= self.SAFE_SKILL_MIN_CONFIDENCE:
            skill = str(slots.get("skill") or intent).strip()
            mapped = self._normalize_skill_name(skill)
            if mapped and self.skill_registry.has_skill(mapped):
                return IntentRouteResult(
                    action="load_skills",
                    source="llm:skill",
                    stage="skill",
                    confidence=confidence,
                    skills=[mapped],
                    model_response=llm_payload,
                )

        if confidence < self.ACTION_MIN_CONFIDENCE:
            return IntentRouteResult(
                action="general_chat",
                source="llm:low_confidence",
                confidence=confidence,
                model_response=llm_payload,
            )

        if domain == "home_assistant":
            reply = await asyncio.to_thread(
                self.home_assistant_service.handle_structured_intent,
                intent,
                slots,
                user,
                session_id,
            )
            if reply:
                return IntentRouteResult(
                    action="direct_response",
                    source="llm:home_assistant",
                    stage="home_assistant",
                    confidence=confidence,
                    reply=reply,
                    model_response=llm_payload,
                )

        if domain == "home":
            reply = await asyncio.to_thread(
                self._handle_home_structured_intent,
                intent,
                slots,
                user,
                session_id,
            )
            if reply:
                return IntentRouteResult(
                    action="direct_response",
                    source="llm:home",
                    stage="home",
                    confidence=confidence,
                    reply=reply,
                    model_response=llm_payload,
                )

        return IntentRouteResult(
            action="general_chat",
            source="llm:general",
            confidence=confidence,
            model_response=llm_payload,
        )

    async def _detect_with_llm(self, text: str) -> dict[str, Any] | None:
        devices = self._home_assistant_devices_for_prompt()
        skills = self.skill_registry.list_skills()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是独立的意图检测模型，只能输出一个 JSON 对象，不能输出解释。\n"
                    "允许的 domain: general, skill, home_assistant, home。\n"
                    "允许的 skill: search, calculator, email。\n"
                    "home_assistant intent: turn_on, turn_off, get_state, list_devices。\n"
                    "home intent: query_inventory, query_expiring_items, add_inventory_item, "
                    "update_inventory_quantity, create_reminder。\n"
                    "如果用户是否定、闲聊、参数缺失或不应自动执行，输出 domain=general 或 confidence<0.7。\n"
                    "输出字段必须是: domain, intent, confidence, slots, reason。\n"
                    "slots 中只放结构化参数，例如 entity_id/entity_alias/name/quantity/unit/"
                    "location/expires_at/title/raw_text/skill。\n"
                    f"当前可用 skill: {', '.join(skills) or '无'}。\n"
                    f"Home Assistant 白名单设备: {json.dumps(devices, ensure_ascii=False)}。"
                ),
            },
            {"role": "user", "content": text},
        ]
        try:
            async with self.llm_factory() as llm_client:
                raw = await llm_client.achat(messages)
        except Exception:
            return None
        return self._parse_json_object(raw)

    def _handle_home_structured_intent(
        self,
        intent: str,
        slots: dict[str, Any],
        user: dict[str, Any],
        session_id: str | None,
    ) -> str | None:
        location = str(slots.get("location") or "fridge")
        if location in {"冰箱", "fridge", "refrigerator"}:
            location = "fridge"

        if intent == "query_expiring_items":
            days = self._coerce_int(slots.get("days"), default=3, minimum=1, maximum=30)
            rows = self.home_service.expiring_items(days=days, location=location)
            if not rows["items"]:
                return f"根据 {rows['generated_at']} 的记录，未来 {days} 天冰箱里没有快过期物品。"
            lines = [f"根据 {rows['generated_at']} 的记录，未来 {days} 天快过期的物品："]
            for item in rows["items"]:
                lines.append(
                    f"- {item.get('name')}：{item.get('quantity') or '未知'}"
                    f"{item.get('unit') or ''}，{item.get('expires_at')} 到期"
                )
            return "\n".join(lines)

        if intent == "query_inventory":
            return self.home_service.handle_home_chat_intent("冰箱里有什么", user, session_id)

        if intent == "add_inventory_item":
            name = str(slots.get("name") or "").strip()
            if not name:
                return None
            payload = {
                "name": name,
                "quantity": self._coerce_quantity(slots.get("quantity")),
                "unit": str(slots.get("unit") or ""),
                "zone": str(slots.get("zone") or "冷藏层"),
                "expires_at": str(slots.get("expires_at") or "") or None,
                "category": str(slots.get("category") or ""),
                "created_from": "intent_llm",
                "source": {"type": "chat", "session_id": session_id},
            }
            result = self.home_service.add_inventory_item(location, payload, user)
            item = result["item"]
            expiry = f"，{item['expires_at']} 到期" if item.get("expires_at") else ""
            return (
                f"已记下：冰箱{item.get('zone') or ''}有 "
                f"{item['quantity'] if item.get('quantity') is not None else '未知'}"
                f"{item.get('unit') or ''}{item['name']}{expiry}。"
            )

        if intent == "update_inventory_quantity":
            name = str(slots.get("name") or "").strip()
            if not name:
                return None
            quantity = self._coerce_quantity(slots.get("quantity"))
            unit = str(slots.get("unit") or "")
            match = self.home_service._first_inventory_by_name(location, name)
            if match:
                result = self.home_service.update_inventory_item(
                    location,
                    match["id"],
                    {"quantity": quantity, "unit": unit},
                    user,
                )
            else:
                result = self.home_service.add_inventory_item(
                    location,
                    {"name": name, "quantity": quantity, "unit": unit, "created_from": "intent_llm"},
                    user,
                )
            item = result["item"]
            return f"已更新冰箱清单：{item['name']} 现在是 {item.get('quantity')}{item.get('unit') or ''}。"

        if intent == "create_reminder":
            title = str(slots.get("title") or slots.get("raw_text") or "").strip()
            if not title:
                return None
            result = self.home_service.create_reminder(
                {
                    "title": title[:40],
                    "description": str(slots.get("description") or f"提醒你{title}"),
                    "raw_text": str(slots.get("raw_text") or title),
                    "channels": ["in_app", "web_push"],
                    "recipients": [user.get("id")],
                    "created_from": "intent_llm",
                },
                user,
            )
            return result["receipt"]

        return None

    def _home_assistant_devices_for_prompt(self) -> list[dict[str, Any]]:
        try:
            entities = self.home_assistant_service.list_allowed_entities().get("entities", [])
        except Exception:
            return []
        return [
            {
                "entity_id": item.get("entity_id"),
                "aliases": item.get("aliases") or [],
                "risk_level": item.get("risk_level"),
                "power_control": item.get("power_control"),
            }
            for item in entities
        ]

    @staticmethod
    def _parse_json_object(raw: str | None) -> dict[str, Any] | None:
        text = (raw or "").strip()
        if not text:
            return None
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
        if fenced:
            text = fenced.group(1)
        elif "{" in text and "}" in text:
            text = text[text.find("{"): text.rfind("}") + 1]
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _coerce_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _coerce_quantity(value: Any) -> float | int | None:
        if value in (None, ""):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return int(numeric) if numeric.is_integer() else numeric

    @staticmethod
    def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return min(max(number, minimum), maximum)

    @staticmethod
    def _normalize_skill_name(name: str) -> str:
        normalized = (name or "").strip().lower()
        aliases = {
            "realtime_search": "search",
            "web_search": "search",
            "search": "search",
            "calculate": "calculator",
            "calculation": "calculator",
            "calculator": "calculator",
            "email": "email",
            "email-sender": "email",
        }
        return aliases.get(normalized, normalized)

    @staticmethod
    def _looks_like_calculation(text: str) -> bool:
        normalized = text.strip()
        if re.fullmatch(r"[\d\s+\-*/().%^]+", normalized):
            return any(op in normalized for op in ["+", "-", "*", "/", "%", "^"])
        return bool(re.search(r"(计算|算一下|等于多少|sqrt|pow)\s*[\d(]", normalized, re.I))
