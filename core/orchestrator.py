"""Agent 编排器"""
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
from queue import Queue
import secrets
from threading import Thread
import time
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional
from agent_runtime import AgentModelResponse, RunStore, ToolApprovalRequired, ToolCall, ToolRegistry
from .conversation import ConversationManager
from .context import ExecutionContext
from .context_compressor import ContextCompressor
from services.llm_client import LLMClient
from skills.registry import SkillRegistry
from utils.parser import InputParser


class AgentOrchestrator:
    """Agent 核心编排器"""
    
    def __init__(
        self,
        llm_client: LLMClient,
        conversation: ConversationManager,
        skill_registry: SkillRegistry,
        context_compressor: Optional[ContextCompressor] = None,
        tool_registry: ToolRegistry | None = None,
        run_store: RunStore | None = None,
        max_steps: int = 12,
        max_runtime_seconds: int = 180,
        max_tool_output_chars: int = 12000,
        checkpoint_callback: Callable[[], Any] | None = None,
    ):
        self.llm_client = llm_client
        self.conversation = conversation
        self.skill_registry = skill_registry
        self.context_compressor = context_compressor
        self.tool_registry = tool_registry
        self.run_store = run_store
        self.max_steps = max(1, max_steps)
        self.max_runtime_seconds = max(1, max_runtime_seconds)
        self.max_tool_output_chars = max(1000, max_tool_output_chars)
        self.checkpoint_callback = checkpoint_callback
        self.run: Dict[str, Any] | None = None
        self.pending_approval_token: str | None = None
        self._run_started_monotonic = 0.0
        self.context = ExecutionContext()
    
    def process_user_input(
        self,
        user_input: str,
        attachments: List[Dict[str, Any]] | None = None,
        images: List[Dict[str, Any]] | None = None,
    ) -> bool:
        """处理用户输入，返回是否继续。同步入口只是 async 主流程的兼容包装。"""
        return self._run_async_sync(
            lambda: self.process_user_input_async(
                user_input,
                attachments=attachments,
                images=images,
            )
        )

    async def process_user_input_async(
        self,
        user_input: str,
        attachments: List[Dict[str, Any]] | None = None,
        images: List[Dict[str, Any]] | None = None,
        auto_skills: List[str] | None = None,
        session_id: str | None = None,
    ) -> bool:
        """异步处理用户输入，返回是否继续。"""
        accepted, _events = self._prepare_user_input(
            user_input,
            attachments=attachments,
            images=images,
            auto_skills=auto_skills,
            emit_events=False,
        )
        if not accepted:
            return True

        self._start_run(session_id=session_id or "cli", goal=user_input)
        await self._checkpoint()
        await self._consume_ai_loop()

        return self.context.should_continue

    def process_user_input_stream(
        self,
        user_input: str,
        attachments: List[Dict[str, Any]] | None = None,
        images: List[Dict[str, Any]] | None = None,
    ) -> Iterator[Dict[str, Any]]:
        """处理用户输入，并逐步产出前端可展示的过程事件。"""
        yield from self._iter_async_sync(
            lambda: self.process_user_input_stream_async(
                user_input,
                attachments=attachments,
                images=images,
            )
        )

    async def process_user_input_stream_async(
        self,
        user_input: str,
        attachments: List[Dict[str, Any]] | None = None,
        images: List[Dict[str, Any]] | None = None,
        auto_skills: List[str] | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """异步处理用户输入，并逐步产出前端可展示的过程事件。"""
        accepted, events = self._prepare_user_input(
            user_input,
            attachments=attachments,
            images=images,
            auto_skills=auto_skills,
            emit_events=True,
        )
        if not accepted:
            yield {"type": "done", "should_continue": self.context.should_continue}
            return

        for event in events:
            yield event

        self._start_run(session_id=session_id or "cli", goal=user_input)
        await self._checkpoint()
        async for event in self._ai_loop_events(stream_model=True):
            yield event
        yield {
            "type": "done",
            "should_continue": self.context.should_continue,
            "run_id": self.run.get("id") if self.run else None,
            "run_status": self.run.get("status") if self.run else None,
        }

    def _prepare_user_input(
        self,
        user_input: str,
        attachments: List[Dict[str, Any]] | None = None,
        images: List[Dict[str, Any]] | None = None,
        auto_skills: List[str] | None = None,
        *,
        emit_events: bool = False,
    ) -> tuple[bool, List[Dict[str, Any]]]:
        """解析用户输入、注入上下文并写入用户消息。"""
        if not (user_input.strip() or attachments or images):
            return False, []

        events: List[Dict[str, Any]] = []
        if emit_events:
            events.append({"type": "step", "stage": "parse", "message": "解析用户输入"})

        skill_name, cleaned_input = InputParser.parse_user_input(user_input)
        loaded_skills: set[str] = set()

        for auto_skill in self._normalize_skill_names(auto_skills):
            if emit_events:
                events.append({
                    "type": "step",
                    "stage": "skill",
                    "message": f"自动加载工具上下文：{auto_skill}",
                })
            if self._load_skill(auto_skill):
                loaded_skills.add(auto_skill)
                if emit_events:
                    events.append({
                        "type": "step",
                        "stage": "skill_loaded",
                        "message": f"工具已激活：{auto_skill}",
                    })
            elif emit_events:
                events.append({
                    "type": "step",
                    "stage": "skill_missing",
                    "message": f"未找到工具：{auto_skill}",
                })

        if skill_name:
            if emit_events:
                events.append({
                    "type": "step",
                    "stage": "skill",
                    "message": f"加载技能上下文：{skill_name}",
                })
            if skill_name in loaded_skills:
                user_input = cleaned_input if cleaned_input else user_input
                if emit_events:
                    events.append({
                        "type": "step",
                        "stage": "skill_loaded",
                        "message": f"技能已激活：{skill_name}",
                    })
            elif self._load_skill(skill_name):
                loaded_skills.add(skill_name)
                user_input = cleaned_input if cleaned_input else user_input
                if emit_events:
                    events.append({
                        "type": "step",
                        "stage": "skill_loaded",
                        "message": f"技能已激活：{skill_name}",
                    })
            else:
                print(f"[警告] 未找到技能：{skill_name}")
                if emit_events:
                    events.append({
                        "type": "step",
                        "stage": "skill_missing",
                        "message": f"未找到技能：{skill_name}",
                    })

        if InputParser.needs_realtime_search(user_input):
            search_skill_loaded = False
            if skill_name != "search" and "search" not in loaded_skills:
                if emit_events:
                    events.append({
                        "type": "step",
                        "stage": "skill",
                        "message": "加载实时查询工具上下文：search",
                    })
                search_skill_loaded = self._load_skill("search")
                if search_skill_loaded:
                    loaded_skills.add("search")
                if emit_events:
                    events.append({
                        "type": "step",
                        "stage": "skill_loaded" if search_skill_loaded else "skill_missing",
                        "message": "实时查询工具已激活：search"
                        if search_skill_loaded
                        else "未找到 search 技能，仅注入实时查询提醒",
                    })
            self.conversation.add_system_message(
                "## 提醒：用户的问题涉及实时信息\n"
                "你的训练数据有截止日期，不具备实时信息。"
                "请调用 http_request 等原生结构化工具获取最新数据。"
                "普通城市天气属于公网实时查询；除非用户明确询问已配置的智能家居实体，"
                "否则不要调用 Home Assistant 工具。"
                "优先使用已加载的 search 技能说明选择稳定来源。"
                "如果某个搜索源或 API 无法访问，必须切换到同类备用来源重试，"
                "然后基于成功获取的结果回答。禁止凭记忆编造实时数据。"
            )
            if emit_events:
                events.append({
                    "type": "step",
                    "stage": "realtime_hint",
                    "message": "检测到实时查询意图，已注入搜索提醒",
                })

        self.conversation.add_system_message(
            "## 当前运行时协议（最高优先级）\n"
            "本运行时只支持原生 function calling。需要行动时必须通过 tool_calls 调用"
            "已提供的工具，不能把工具调用写成普通回复。工具结果返回后继续行动或给出"
            "最终答案。技能内容仅提供选源、知识和操作步骤。"
        )

        self.conversation.add_user_message(
            user_input,
            attachments=attachments,
            images=images,
        )
        if emit_events:
            events.append({
                "type": "step",
                "stage": "conversation",
                "message": "用户消息已写入上下文",
            })

        return True, events

    @staticmethod
    def _normalize_skill_names(skill_names: List[str] | None) -> List[str]:
        seen: set[str] = set()
        normalized: List[str] = []
        for name in skill_names or []:
            value = (name or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized
    
    def _load_skill(self, skill_name: str) -> bool:
        """加载技能"""
        skill = self.skill_registry.get(skill_name)
        if not skill:
            return False
        
        skill_content = skill.load_context()
        self.conversation.inject_skill_context(skill_name, skill_content)
        self.context.activate_skill(skill_name)
        print(f"[加载技能]: {skill_name}")
        return True
    
    async def _consume_ai_loop(self) -> None:
        """运行 AI 循环但不向调用方暴露过程事件。"""
        async for _event in self._ai_loop_events(stream_model=False):
            pass

    async def _ai_loop_events(self, *, stream_model: bool) -> AsyncIterator[Dict[str, Any]]:
        """Run the native function-calling loop without text-protocol fallback."""
        if not self._structured_tools_available():
            message = "当前模型适配器不支持原生 function calling，无法启动 Agent Runtime。"
            self.context.stop()
            self._update_run(status="failed", pending_approval=None, error=message)
            yield {"type": "error", "stage": "capability", "message": message}
            return
        async for event in self._structured_ai_loop_events(stream_model=stream_model):
            yield event

    def _structured_tools_available(self) -> bool:
        return bool(
            self.tool_registry
            and self.tool_registry.list()
            and callable(getattr(self.llm_client, "achat_with_tools", None))
        )

    async def _structured_ai_loop_events(
        self,
        *,
        stream_model: bool,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Native function-calling loop with budgets, approvals and checkpoints."""
        iteration = 0
        while True:
            if self._budget_exceeded(iteration):
                message = self._stop_for_budget()
                yield {"type": "step", "stage": "budget_exceeded", "message": message}
                break
            iteration += 1
            yield {
                "type": "step",
                "stage": "context",
                "message": "构建结构化工具上下文",
                "iteration": iteration,
            }
            messages, context_node_ids = await self._build_model_context()
            schemas = self.tool_registry.schemas() if self.tool_registry else []
            yield {
                "type": "model_start",
                "stage": "model",
                "message": "发送原生 function calling 请求",
                "iteration": iteration,
                "model": self.llm_client.model,
                "message_count": len(messages),
                "tool_count": len(schemas),
            }

            response: AgentModelResponse
            if stream_model and hasattr(self.llm_client, "astream_with_tools"):
                response = AgentModelResponse()
                async for item in self.llm_client.astream_with_tools(messages, schemas):
                    if item.get("type") == "content_delta":
                        yield {
                            "type": "model_delta",
                            "stage": "model",
                            "iteration": iteration,
                            "delta": item.get("delta") or "",
                        }
                    elif item.get("type") == "done":
                        response = item["response"]
            else:
                response = await self.llm_client.achat_with_tools(messages, schemas)

            tool_payloads = [call.as_openai() for call in response.tool_calls]
            self.conversation.add_assistant_message(
                response.content,
                tool_calls=tool_payloads or None,
            )
            self._record_context_nodes(context_node_ids)
            await self._checkpoint()
            self._append_run_step({
                "kind": "model",
                "iteration": iteration,
                "content": response.content,
                "tool_calls": [call.as_dict() for call in response.tool_calls],
                "finish_reason": response.finish_reason,
            })
            yield {
                "type": "model_done",
                "stage": "model",
                "message": "模型输出完成",
                "iteration": iteration,
                "content": response.content,
                "tool_calls": [call.as_dict() for call in response.tool_calls],
            }

            if not response.tool_calls:
                self.context.stop()
                self._update_run(status="completed", pending_approval=None)
                yield {
                    "type": "step",
                    "stage": "complete",
                    "message": "任务完成",
                    "iteration": iteration,
                }
                break

            paused, tool_events = await self._execute_tool_calls(response.tool_calls)
            for event in tool_events:
                yield {**event, "iteration": iteration}
            if paused:
                break

    async def _execute_tool_calls(
        self,
        calls: List[ToolCall],
        *,
        first_call_approved: bool = False,
    ) -> tuple[bool, List[Dict[str, Any]]]:
        events: List[Dict[str, Any]] = []
        for index, call in enumerate(calls):
            events.append({
                "type": "tool_start",
                "stage": "tool",
                "message": f"调用工具：{call.name}",
                "tool_call": call.as_dict(),
            })
            try:
                result = await self.tool_registry.invoke(
                    call,
                    approved=first_call_approved and index == 0,
                )
            except ToolApprovalRequired as approval:
                token = secrets.token_urlsafe(24)
                self.pending_approval_token = token
                pending = {
                    "tool_call": approval.call.as_dict(),
                    "remaining_tool_calls": [item.as_dict() for item in calls[index + 1:]],
                    "token_hash": self._token_hash(token),
                    "risk_level": approval.definition.risk_level,
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                }
                self._update_run(status="waiting_approval", pending_approval=pending)
                events.append({
                    "type": "approval_required",
                    "stage": "approval",
                    "message": f"工具 {call.name} 需要确认后才能执行",
                    "run_id": self.run.get("id") if self.run else None,
                    "approval_token": token,
                    "risk_level": approval.definition.risk_level,
                    "tool_call": call.as_dict(),
                })
                return True, events

            content = result.model_content(self.max_tool_output_chars)
            self.conversation.add_tool_message(call.id, call.name, content)
            await self._checkpoint()
            self._append_run_step({"kind": "tool", "tool_result": result.as_dict()})
            events.append({
                "type": "tool_result",
                "stage": "tool",
                "message": "工具执行完成" if result.success else "工具执行失败",
                "tool_call": call.as_dict(),
                "tool_result": result.as_dict(),
                "success": result.success,
                "output": content,
            })
        return False, events

    async def resume_after_approval_stream_async(
        self,
        run_id: str,
        approval_token: str,
        *,
        approved: bool = True,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Resume a checkpointed run after a one-time approval decision."""
        if not self.run_store:
            raise RuntimeError("run_store_not_configured")
        self.run = self.run_store.load(run_id)
        pending = self.run.get("pending_approval") or {}
        if self.run.get("status") != "waiting_approval" or not pending:
            raise ValueError("run_is_not_waiting_for_approval")
        expected = str(pending.get("token_hash") or "")
        if not expected or not hmac.compare_digest(expected, self._token_hash(approval_token)):
            raise PermissionError("invalid_approval_token")
        self.pending_approval_token = None
        self._run_started_monotonic = time.monotonic()

        call = ToolCall.from_dict(pending["tool_call"])
        remaining = [ToolCall.from_dict(item) for item in pending.get("remaining_tool_calls") or []]
        if not approved:
            self._update_run(status="cancelled", pending_approval=None)
            self.conversation.add_tool_message(
                call.id,
                call.name,
                '{"status":"cancelled","error":"user_rejected"}',
            )
            await self._checkpoint()
            self.context.stop()
            yield {
                "type": "done",
                "stage": "cancelled",
                "message": "用户已拒绝工具调用",
                "run_id": run_id,
                "run_status": "cancelled",
            }
            return

        self._update_run(status="running", pending_approval=None)
        paused, events = await self._execute_tool_calls(
            [call, *remaining],
            first_call_approved=True,
        )
        for event in events:
            yield event
        if not paused:
            async for event in self._structured_ai_loop_events(stream_model=True):
                yield event
        yield {
            "type": "done",
            "stage": "done",
            "message": "响应完成",
            "run_id": run_id,
            "run_status": self.run.get("status") if self.run else None,
        }

    async def resume_run_stream_async(self, run_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Continue an interrupted structured run from its last durable step."""
        if not self.run_store:
            raise RuntimeError("run_store_not_configured")
        self.run = self.run_store.load(run_id)
        status = self.run.get("status")
        if status == "waiting_approval":
            raise ValueError("run_requires_approval")
        if status in RunStore.TERMINAL_STATUSES:
            raise ValueError(f"run_is_terminal:{status}")
        if not self._structured_tools_available():
            raise RuntimeError("structured_tools_not_available")
        self._run_started_monotonic = time.monotonic()
        self.context = ExecutionContext()
        self._update_run(status="running", interrupted_reason=None)

        steps = list(self.run.get("steps") or [])
        last_model_index = next(
            (index for index in range(len(steps) - 1, -1, -1) if steps[index].get("kind") == "model"),
            -1,
        )
        if last_model_index >= 0:
            model_step = steps[last_model_index]
            calls = [ToolCall.from_dict(item) for item in model_step.get("tool_calls") or []]
            completed_ids = {
                str((step.get("tool_result") or {}).get("call_id") or "")
                for step in steps[last_model_index + 1:]
                if step.get("kind") == "tool"
            }
            conversation_messages = self.conversation.get_messages()
            completed_ids.update(
                str(message.get("tool_call_id") or "")
                for message in conversation_messages
                if message.get("role") == "tool"
            )
            stored_call_ids = {
                str(raw.get("id") or "")
                for message in conversation_messages
                for raw in (message.get("tool_calls") or [])
            }
            if calls and not all(call.id in stored_call_ids for call in calls):
                self.conversation.add_assistant_message(
                    str(model_step.get("content") or ""),
                    tool_calls=[call.as_openai() for call in calls],
                )
                await self._checkpoint()
            remaining = [call for call in calls if call.id not in completed_ids]
            if remaining:
                paused, events = await self._execute_tool_calls(remaining)
                for event in events:
                    yield event
                if paused:
                    return
            elif not calls and model_step.get("content"):
                self.context.stop()
                self._update_run(status="completed")
                yield {
                    "type": "done",
                    "stage": "done",
                    "message": "任务已在中断前完成",
                    "run_id": run_id,
                    "run_status": "completed",
                }
                return

        else:
            conversation_calls = self._latest_conversation_tool_calls()
            completed_ids = {
                str(message.get("tool_call_id") or "")
                for message in self.conversation.get_messages()
                if message.get("role") == "tool"
            }
            remaining = [call for call in conversation_calls if call.id not in completed_ids]
            if remaining:
                paused, events = await self._execute_tool_calls(remaining)
                for event in events:
                    yield event
                if paused:
                    return

        async for event in self._structured_ai_loop_events(stream_model=True):
            yield event
        yield {
            "type": "done",
            "stage": "done",
            "message": "恢复执行完成",
            "run_id": run_id,
            "run_status": self.run.get("status") if self.run else None,
        }

    def mark_interrupted(self, reason: str) -> None:
        if self.run and self.run.get("status") == "running":
            self._update_run(status="interrupted", interrupted_reason=reason)

    def _latest_conversation_tool_calls(self) -> List[ToolCall]:
        for message in reversed(self.conversation.get_messages()):
            raw_calls = message.get("tool_calls") or []
            if not raw_calls:
                continue
            calls: List[ToolCall] = []
            for index, raw in enumerate(raw_calls):
                function = raw.get("function") or {}
                arguments = function.get("arguments") or "{}"
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except Exception:
                        arguments = {"__invalid_json__": arguments}
                calls.append(ToolCall(
                    id=str(raw.get("id") or f"recovered_call_{index}"),
                    name=str(function.get("name") or ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                ))
            return calls
        return []

    def resume_after_approval(
        self,
        run_id: str,
        approval_token: str,
        *,
        approved: bool = True,
    ) -> List[Dict[str, Any]]:
        return list(self._iter_async_sync(lambda: self.resume_after_approval_stream_async(
            run_id,
            approval_token,
            approved=approved,
        )))

    def _start_run(self, *, session_id: str, goal: str) -> None:
        active_skill = self.context.active_skill
        self.context = ExecutionContext(active_skill=active_skill)
        self._run_started_monotonic = time.monotonic()
        if self.run_store:
            self.run = self.run_store.create(
                session_id=session_id,
                goal=goal,
                max_steps=self.max_steps,
                max_runtime_seconds=self.max_runtime_seconds,
            )
        else:
            self.run = {
                "id": None,
                "session_id": session_id,
                "goal": goal,
                "status": "running",
                "steps": [],
                "step_count": 0,
            }

    def _append_run_step(self, step: Dict[str, Any]) -> None:
        if not self.run:
            return
        if self.run_store and self.run.get("id"):
            self.run = self.run_store.append_step(self.run, step)
        else:
            self.run.setdefault("steps", []).append(step)
            self.run["step_count"] = len(self.run["steps"])

    def _update_run(self, **changes: Any) -> None:
        if not self.run:
            return
        if self.run_store and self.run.get("id"):
            self.run = self.run_store.update(self.run, **changes)
        else:
            self.run.update(changes)

    async def _checkpoint(self) -> None:
        if not self.checkpoint_callback:
            return
        value = self.checkpoint_callback()
        if asyncio.iscoroutine(value):
            await value

    def _budget_exceeded(self, iteration: int) -> bool:
        step_count = int((self.run or {}).get("step_count") or iteration)
        elapsed = time.monotonic() - self._run_started_monotonic
        return step_count >= self.max_steps or elapsed >= self.max_runtime_seconds

    def _stop_for_budget(self) -> str:
        message = (
            f"Agent 执行预算已用尽：最多 {self.max_steps} 步、"
            f"最长 {self.max_runtime_seconds} 秒。"
        )
        self.conversation.add_assistant_message(message)
        self.context.stop()
        self._update_run(status="budget_exceeded", pending_approval=None, error=message)
        return message

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256((token or "").encode("utf-8")).hexdigest()

    async def _build_model_context(self) -> tuple[List[Dict[str, Any]], List[str]]:
        """构建模型请求上下文，并返回本轮 assistant 需要记录的上下文节点。"""
        context_node_ids: List[str] = []
        if (self.conversation.branch_engine is not None
                and self.conversation.active_node_id is not None):
            branch_messages = self.conversation.branch_engine.build_context(
                self.conversation.active_node_id
            )
            context_node_ids = [
                msg["node_id"] for msg in branch_messages if "node_id" in msg
            ]
            if self.context_compressor:
                messages = await self.context_compressor.build_messages_async(self.conversation)
            else:
                messages = branch_messages
        elif self.context_compressor:
            messages = await self.context_compressor.build_messages_async(self.conversation)
        else:
            messages = self.conversation.get_messages()
        return messages, context_node_ids

    def _record_context_nodes(self, context_node_ids: List[str]) -> None:
        if context_node_ids and self.conversation._messages:
            self.conversation._messages[-1]["context_nodes"] = context_node_ids

    @staticmethod
    def _run_async_sync(coro_factory: Callable[[], Any]) -> Any:
        """Run an async coroutine from sync callers without duplicating logic."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro_factory())

        results: Queue[tuple[bool, Any]] = Queue(maxsize=1)

        def runner():
            try:
                results.put((True, asyncio.run(coro_factory())))
            except BaseException as exc:
                results.put((False, exc))

        thread = Thread(target=runner, daemon=True)
        thread.start()
        ok, value = results.get()
        thread.join()
        if ok:
            return value
        raise value

    @staticmethod
    def _iter_async_sync(async_iter_factory: Callable[[], AsyncIterator[Dict[str, Any]]]) -> Iterator[Dict[str, Any]]:
        """Expose an async event stream as a sync iterator for legacy callers."""
        results: Queue[tuple[str, Any]] = Queue()

        async def consume():
            async for event in async_iter_factory():
                results.put(("item", event))

        def runner():
            try:
                asyncio.run(consume())
            except BaseException as exc:
                results.put(("error", exc))
            finally:
                results.put(("done", None))

        thread = Thread(target=runner, daemon=True)
        thread.start()
        while True:
            kind, value = results.get()
            if kind == "item":
                yield value
            elif kind == "error":
                thread.join()
                raise value
            else:
                thread.join()
                break
