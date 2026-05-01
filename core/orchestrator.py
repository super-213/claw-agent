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
    ):
        self.llm_client = llm_client
        self.conversation = conversation
        self.skill_registry = skill_registry
        self.executor = executor
        self.context_compressor = context_compressor
        self.context = ExecutionContext()
        
        # 构建责任链：完成 -> 命令 -> 技能输出 -> 默认
        self.handler_chain = CompletionHandler(
            CommandHandler(
                executor,
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
            # 获取 AI 回复
            if self.context_compressor:
                messages = self.context_compressor.build_messages(self.conversation)
            else:
                messages = self.conversation.get_messages()
            reply = self.llm_client.chat(messages)
            
            print(f"\n[AI 回复]:\n{reply}\n")
            self.conversation.add_assistant_message(reply)
            
            # 使用责任链处理回复
            result = self.handler_chain.handle(reply, self.context)
            
            if result == HandlerResult.BREAK:
                break
            elif result == HandlerResult.CONTINUE:
                # 命令执行后，添加执行结果
                if exec_result := self.context.metadata.get('execution_result'):
                    output = exec_result.output if exec_result.success else exec_result.error
                    self.conversation.add_user_message(f"[执行完成]\n{output}")
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
            if self.context_compressor:
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

            yield {
                "type": "step",
                "stage": "handler",
                "message": "解析模型回复",
                "iteration": iteration,
            }
            command = self._extract_command(reply)
            if command:
                yield {
                    "type": "command_start",
                    "stage": "command",
                    "message": f"执行命令：{command}",
                    "iteration": iteration,
                    "command": command,
                }

            result = self.handler_chain.handle(reply, self.context)

            if command:
                exec_result = self.context.metadata.get("execution_result")
                if exec_result:
                    output = exec_result.output if exec_result.success else exec_result.error
                    yield {
                        "type": "command_result",
                        "stage": "command",
                        "message": "命令执行完成" if exec_result.success else "命令执行失败",
                        "iteration": iteration,
                        "command": command,
                        "success": exec_result.success,
                        "return_code": exec_result.return_code,
                        "output": output or "",
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
                    output = exec_result.output if exec_result.success else exec_result.error
                    self.conversation.add_user_message(f"[执行完成]\n{output}")
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
        if "[命令]" not in response:
            return ""
        return response.split("[命令]", 1)[1].strip().split("\n", 1)[0].strip()
