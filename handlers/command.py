"""命令处理器"""
from .base import ResponseHandler, HandlerResult
from core.context import ExecutionContext
from services.executor import CommandExecutor


class CommandHandler(ResponseHandler):
    """处理 [命令] 标记"""
    
    def __init__(self, executor: CommandExecutor, next_handler=None):
        super().__init__(next_handler)
        self.executor = executor
    
    def can_handle(self, response: str, context: ExecutionContext) -> bool:
        return "[命令]" in response
    
    def process(self, response: str, context: ExecutionContext) -> HandlerResult:
        # 提取命令
        command = response.split("[命令]")[1].strip().split('\n')[0].strip()
        print(f"[执行命令]: {command}")
        
        # 执行命令
        result = self.executor.execute(command)
        
        if result.error:
            print(f"[执行错误]: {result.error}\n")
            context.metadata['last_error'] = result.error
        else:
            print(f"[执行结果]:\n{result.output}\n")
            context.metadata['last_output'] = result.output
        
        # 保存命令和结果到上下文
        context.last_command = command
        context.metadata['execution_result'] = result
        
        return HandlerResult.CONTINUE
