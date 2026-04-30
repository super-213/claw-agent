"""Agent 编排器"""
from typing import Optional
from .conversation import ConversationManager
from .context import ExecutionContext
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
        executor: CommandExecutor
    ):
        self.llm_client = llm_client
        self.conversation = conversation
        self.skill_registry = skill_registry
        self.executor = executor
        self.context = ExecutionContext()
        
        # 构建责任链：完成 -> 命令 -> 技能输出 -> 默认
        self.handler_chain = CompletionHandler(
            CommandHandler(
                executor,
                SkillOutputHandler()
            )
        )
    
    def process_user_input(self, user_input: str) -> bool:
        """处理用户输入，返回是否继续"""
        if not user_input.strip():
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
        self.conversation.add_user_message(user_input)
        
        # 处理 AI 回复循环
        self._process_ai_loop()
        
        return self.context.should_continue
    
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
