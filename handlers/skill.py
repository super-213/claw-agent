"""技能输出处理器"""
import re
from .base import ResponseHandler, HandlerResult
from core.context import ExecutionContext


class SkillOutputHandler(ResponseHandler):
    """处理技能自定义输出格式"""
    
    def can_handle(self, response: str, context: ExecutionContext) -> bool:
        # 只在技能激活时处理
        if not context.active_skill:
            return False
        # 检查是否包含技能标记（如 [计算]、[天气] 等）
        return bool(re.search(r'\[\S+\]', response))
    
    def process(self, response: str, context: ExecutionContext) -> HandlerResult:
        print(f"[技能输出]: {context.active_skill}")
        print("任务完成\n")
        context.reset_skill()
        context.stop()
        return HandlerResult.BREAK
