"""Agent 编排器"""
import asyncio
from queue import Queue
from threading import Thread
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional
from .conversation import ConversationManager
from .context import ExecutionContext
from .context_compressor import ContextCompressor
from services.llm_client import LLMClient
from services.executor import CommandExecutor
from skills.registry import SkillRegistry
from handlers import CommandHandler, CompletionHandler, SkillOutputHandler, HandlerResult
from utils.parser import InputParser


class AgentOrchestrator:
    """Agent 核心编排器"""
    
    def __init__(
        self,
        llm_client: LLMClient,
        conversation: ConversationManager,
        skill_registry: SkillRegistry,
        executor: CommandExecutor,
        context_compressor: Optional[ContextCompressor] = None,
        max_command_failures: int = 3,
    ):
        self.llm_client = llm_client
        self.conversation = conversation
        self.skill_registry = skill_registry
        self.executor = executor
        self.context_compressor = context_compressor
        self.max_command_failures = max_command_failures
        self.context = ExecutionContext()
        
        # 命令优先于完成标记，避免模型在同一回复里输出 [完成] 和 [命令]
        # 时跳过真实执行。
        self.handler_chain = CommandHandler(
            executor,
            CompletionHandler(
                SkillOutputHandler()
            )
        )
    
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

        async for event in self._ai_loop_events(stream_model=True):
            yield event
        yield {"type": "done", "should_continue": self.context.should_continue}

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
                "请先使用 [命令] curl 等方式获取最新数据，"
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
        """处理 AI 回复循环；需要流式展示时产出过程事件。"""
        iteration = 0
        while True:
            iteration += 1
            if stream_model:
                yield {
                    "type": "step",
                    "stage": "context",
                    "message": "构建模型上下文",
                    "iteration": iteration,
                }

            messages, context_node_ids = await self._build_model_context()

            if stream_model:
                reply = ""
                yield {
                    "type": "model_start",
                    "stage": "model",
                    "message": "发送模型请求",
                    "iteration": iteration,
                    "model": self.llm_client.model,
                    "message_count": len(messages),
                }
                reply_parts: List[str] = []
                async for delta in self.llm_client.astream_chat(messages):
                    reply_parts.append(delta)
                    yield {
                        "type": "model_delta",
                        "stage": "model",
                        "iteration": iteration,
                        "delta": delta,
                    }

                reply = "".join(reply_parts)
                yield {
                    "type": "model_done",
                    "stage": "model",
                    "message": "模型输出完成",
                    "iteration": iteration,
                    "content": reply,
                }
            else:
                reply = await self.llm_client.achat(messages)

            print(f"\n[AI 回复]:\n{reply}\n")
            self.conversation.add_assistant_message(reply)

            self._record_context_nodes(context_node_ids)

            if stream_model:
                yield {
                    "type": "step",
                    "stage": "handler",
                    "message": "解析模型回复",
                    "iteration": iteration,
                }
            commands = self._extract_commands(reply)
            command = "\n\n".join(commands)
            if stream_model and commands:
                yield {
                    "type": "command_start",
                    "stage": "command",
                    "message": f"执行命令：{command}",
                    "iteration": iteration,
                    "command": command,
                }

            result = await asyncio.to_thread(
                self.handler_chain.handle,
                reply,
                self.context,
            )

            if stream_model and commands:
                exec_result = self.context.metadata.get("execution_result")
                if exec_result:
                    yield {
                        "type": "command_result",
                        "stage": "command",
                        "message": "命令执行完成" if exec_result.success else "命令执行失败",
                        "iteration": iteration,
                        "command": command,
                        "success": exec_result.success,
                        "return_code": exec_result.return_code,
                        "output": exec_result.feedback,
                    }

            if result == HandlerResult.BREAK:
                if stream_model:
                    yield {
                        "type": "step",
                        "stage": "complete",
                        "message": "任务完成",
                        "iteration": iteration,
                    }
                break
            elif result == HandlerResult.CONTINUE:
                if exec_result := self.context.metadata.get("execution_result"):
                    if self._command_failure_limit_reached(exec_result):
                        abort_message = self._record_command_abort(exec_result)
                        if stream_model:
                            yield {
                                "type": "step",
                                "stage": "command_abort",
                                "message": abort_message,
                                "iteration": iteration,
                            }
                        break
                    self.conversation.add_user_message(f"[执行完成]\n{exec_result.feedback}")
                    if stream_model:
                        yield {
                            "type": "step",
                            "stage": "conversation",
                            "message": "命令结果已写回上下文，继续请求模型",
                            "iteration": iteration,
                        }
                continue
            elif result == HandlerResult.RETRY:
                self.conversation.add_user_message(
                    "请严格按照格式回复：[命令]XXX 或 [完成]XXX"
                )
                if stream_model:
                    yield {
                        "type": "step",
                        "stage": "retry",
                        "message": "模型回复格式不符合协议，已追加格式提醒",
                        "iteration": iteration,
                    }
                continue

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

    @staticmethod
    def _extract_command(response: str) -> str:
        return InputParser.extract_command(response)

    @staticmethod
    def _extract_commands(response: str) -> List[str]:
        return InputParser.extract_commands(response)

    def _command_failure_limit_reached(self, exec_result) -> bool:
        if exec_result.success:
            return False
        return (
            self.context.metadata.get("command_failure_count", 0)
            >= self.max_command_failures
        )

    def _record_command_abort(self, exec_result) -> str:
        failure_count = self.context.metadata.get("command_failure_count", 0)
        message = (
            f"命令连续失败 {failure_count} 次，已停止自动重试。"
            f"最后一次错误：\n{exec_result.feedback}"
        )
        self.conversation.add_user_message(f"[执行中止]\n{message}")
        print(message)
        return message
