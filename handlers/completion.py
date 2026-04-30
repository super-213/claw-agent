"""完成处理器"""
from .base import ResponseHandler, HandlerResult
from core.context import ExecutionContext


class CompletionHandler(ResponseHandler):
    """处理 [完成] 标记"""
    
    def can_handle(self, response: str, context: ExecutionContext) -> bool:
        return "[完成]" in response
    
    def process(self, response: str, context: ExecutionContext) -> HandlerResult:
        print("任务完成\n")
        context.reset_skill()
        context.stop()
        return HandlerResult.BREAK
