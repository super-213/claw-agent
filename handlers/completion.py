"""完成处理器"""
from .base import ResponseHandler, HandlerResult
from core.context import ExecutionContext


class CompletionHandler(ResponseHandler):
    """处理 [完成] 标记"""

    FAILURE_ACK_WORDS = (
        "失败", "未", "无法", "不能", "没有", "不存在", "错误", "报错",
        "failed", "failure", "error", "not ", "no ", "cannot", "can't",
    )
    
    def can_handle(self, response: str, context: ExecutionContext) -> bool:
        return "[完成]" in response
    
    def process(self, response: str, context: ExecutionContext) -> HandlerResult:
        last_result = context.metadata.get("execution_result")
        if last_result and not last_result.success and not self._acknowledges_failure(response):
            print("上一条命令失败，拒绝以成功状态完成\n")
            return HandlerResult.CONTINUE

        print("任务完成\n")
        context.reset_skill()
        context.stop()
        return HandlerResult.BREAK

    def _acknowledges_failure(self, response: str) -> bool:
        normalized = response.lower()
        return any(word in normalized for word in self.FAILURE_ACK_WORDS)
