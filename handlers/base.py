"""响应处理器基类"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from core.context import ExecutionContext


class HandlerResult(Enum):
    """处理结果"""
    CONTINUE = "continue"      # 继续处理
    BREAK = "break"            # 结束循环
    RETRY = "retry"            # 重试请求


class ResponseHandler(ABC):
    """响应处理器基类（责任链模式）"""
    
    def __init__(self, next_handler: Optional['ResponseHandler'] = None):
        self._next = next_handler
    
    def handle(self, response: str, context: ExecutionContext) -> HandlerResult:
        """处理响应"""
        if self.can_handle(response, context):
            return self.process(response, context)
        elif self._next:
            return self._next.handle(response, context)
        else:
            return self.default_action(response, context)
    
    @abstractmethod
    def can_handle(self, response: str, context: ExecutionContext) -> bool:
        """判断是否可以处理"""
        pass
    
    @abstractmethod
    def process(self, response: str, context: ExecutionContext) -> HandlerResult:
        """处理逻辑"""
        pass
    
    def default_action(self, response: str, context: ExecutionContext) -> HandlerResult:
        """默认动作（格式不正确时）"""
        print("AI 未按格式回复，提醒重新生成...")
        return HandlerResult.RETRY
