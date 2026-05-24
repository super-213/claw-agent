"""Agent 编排器"""
from typing import Any, Dict, Iterator, List, Optional
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
        """处理用户输入，返回是否继续"""
        if not user_input.strip() and not attachments and not images:
            return True
        
        # 解析技能调用
        skill_name, cleaned_input = InputParser.parse_user_input(user_input)
        
        # 加载技能
        if skill_name:
            if self._load_skill(skill_name):
                user_input = cleaned_input if cleaned_input else user_input
            else:
                print(f"[警告] 未找到技能：{skill_name}")

        # 检测实时查询意图，注入搜索提醒
        if InputParser.needs_realtime_search(user_input):
            self.conversation.add_system_message(
                "## 提醒：用户的问题涉及实时信息\n"
                "你的训练数据有截止日期，不具备实时信息。"
                "请先使用 [命令] curl 等方式搜索获取最新数据，"
                "然后基于搜索结果回答。禁止凭记忆编造实时数据。"
            )
        
        # 添加用户消息
        self.conversation.add_user_message(
            user_input,
            attachments=attachments,
            images=images,
        )
        
        # 处理 AI 回复循环
        self._process_ai_loop()
        
        return self.context.should_continue

    def process_user_input_stream(
        self,
        user_input: str,
        attachments: List[Dict[str, Any]] | None = None,
        images: List[Dict[str, Any]] | None = None,
    ) -> Iterator[Dict[str, Any]]:
        """处理用户输入，并逐步产出前端可展示的过程事件。"""
        if not user_input.strip() and not attachments and not images:
            yield {"type": "done", "should_continue": self.context.should_continue}
            return

        yield {"type": "step", "stage": "parse", "message": "解析用户输入"}
        skill_name, cleaned_input = InputParser.parse_user_input(user_input)

        if skill_name:
            yield {
                "type": "step",
                "stage": "skill",
                "message": f"加载技能上下文：{skill_name}",
            }
            if self._load_skill(skill_name):
                user_input = cleaned_input if cleaned_input else user_input
                yield {
                    "type": "step",
                    "stage": "skill_loaded",
                    "message": f"技能已激活：{skill_name}",
                }
            else:
                yield {
                    "type": "step",
                    "stage": "skill_missing",
                    "message": f"未找到技能：{skill_name}",
                }

        # 检测实时查询意图，注入搜索提醒
        if InputParser.needs_realtime_search(user_input):
            self.conversation.add_system_message(
                "## 提醒：用户的问题涉及实时信息\n"
                "你的训练数据有截止日期，不具备实时信息。"
                "请先使用 [命令] curl 等方式搜索获取最新数据，"
                "然后基于搜索结果回答。禁止凭记忆编造实时数据。"
            )
            yield {
                "type": "step",
                "stage": "realtime_hint",
                "message": "检测到实时查询意图，已注入搜索提醒",
            }

        self.conversation.add_user_message(
            user_input,
            attachments=attachments,
            images=images,
        )
        yield {"type": "step", "stage": "conversation", "message": "用户消息已写入上下文"}

        yield from self._process_ai_loop_stream()
        yield {"type": "done", "should_continue": self.context.should_continue}
    
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
    
    def _process_ai_loop(self):
        """处理 AI 回复循环"""
        while True:
            # 构建上下文消息
            context_node_ids: List[str] = []
            if (self.conversation.branch_engine is not None
                    and self.conversation.active_node_id is not None):
                # 从分支树构建上下文路径
                branch_messages = self.conversation.branch_engine.build_context(
                    self.conversation.active_node_id
                )
                context_node_ids = [
                    msg["node_id"] for msg in branch_messages if "node_id" in msg
                ]
                # 如果有上下文压缩器，仍然走压缩流程（内部会调用 get_messages 获取分支路径）
                if self.context_compressor:
                    messages = self.context_compressor.build_messages(self.conversation)
                else:
                    messages = branch_messages
            elif self.context_compressor:
                messages = self.context_compressor.build_messages(self.conversation)
            else:
                messages = self.conversation.get_messages()

            # 获取 AI 回复
            reply = self.llm_client.chat(messages)
            
            print(f"\n[AI 回复]:\n{reply}\n")
            self.conversation.add_assistant_message(reply)

            # 记录 context_nodes 到 assistant 消息
            if context_node_ids and self.conversation._messages:
                self.conversation._messages[-1]["context_nodes"] = context_node_ids
            
            # 使用责任链处理回复
            result = self.handler_chain.handle(reply, self.context)
            
            if result == HandlerResult.BREAK:
                break
            elif result == HandlerResult.CONTINUE:
                # 命令执行后，添加执行结果
                if exec_result := self.context.metadata.get('execution_result'):
                    if self._command_failure_limit_reached(exec_result):
                        self._record_command_abort(exec_result)
                        break
                    self.conversation.add_user_message(f"[执行完成]\n{exec_result.feedback}")
                continue
            elif result == HandlerResult.RETRY:
                # 格式不正确，提醒 AI
                self.conversation.add_user_message(
                    "请严格按照格式回复：[命令]XXX 或 [完成]XXX"
                )
                continue

    def _process_ai_loop_stream(self) -> Iterator[Dict[str, Any]]:
        """处理 AI 回复循环，并输出模型调用、解析和命令执行事件。"""
        iteration = 0
        while True:
            iteration += 1
            yield {
                "type": "step",
                "stage": "context",
                "message": "构建模型上下文",
                "iteration": iteration,
            }
            context_node_ids: List[str] = []
            if (self.conversation.branch_engine is not None
                    and self.conversation.active_node_id is not None):
                # 从分支树构建上下文路径
                branch_messages = self.conversation.branch_engine.build_context(
                    self.conversation.active_node_id
                )
                context_node_ids = [
                    msg["node_id"] for msg in branch_messages if "node_id" in msg
                ]
                # 如果有上下文压缩器，仍然走压缩流程（内部会调用 get_messages 获取分支路径）
                if self.context_compressor:
                    messages = self.context_compressor.build_messages(self.conversation)
                else:
                    messages = branch_messages
            elif self.context_compressor:
                messages = self.context_compressor.build_messages(self.conversation)
            else:
                messages = self.conversation.get_messages()

            yield {
                "type": "model_start",
                "stage": "model",
                "message": "发送模型请求",
                "iteration": iteration,
                "model": self.llm_client.model,
                "message_count": len(messages),
            }
            reply_parts: List[str] = []
            for delta in self.llm_client.stream_chat(messages):
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

            print(f"\n[AI 回复]:\n{reply}\n")
            self.conversation.add_assistant_message(reply)

            # 记录 context_nodes 到 assistant 消息
            if context_node_ids and self.conversation._messages:
                self.conversation._messages[-1]["context_nodes"] = context_node_ids

            yield {
                "type": "step",
                "stage": "handler",
                "message": "解析模型回复",
                "iteration": iteration,
            }
            commands = self._extract_commands(reply)
            command = "\n\n".join(commands)
            if commands:
                yield {
                    "type": "command_start",
                    "stage": "command",
                    "message": f"执行命令：{command}",
                    "iteration": iteration,
                    "command": command,
                }

            result = self.handler_chain.handle(reply, self.context)

            if commands:
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
                        yield {
                            "type": "step",
                            "stage": "command_abort",
                            "message": abort_message,
                            "iteration": iteration,
                        }
                        break
                    self.conversation.add_user_message(f"[执行完成]\n{exec_result.feedback}")
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
                yield {
                    "type": "step",
                    "stage": "retry",
                    "message": "模型回复格式不符合协议，已追加格式提醒",
                    "iteration": iteration,
                }
                continue

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
