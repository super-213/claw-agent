"""命令处理器"""
from typing import TYPE_CHECKING

from .base import ResponseHandler, HandlerResult
from utils.parser import InputParser

if TYPE_CHECKING:
    from core.context import ExecutionContext
    from services.executor import CommandExecutor


class CommandHandler(ResponseHandler):
    """处理 [命令] 标记"""
    
    def __init__(self, executor: "CommandExecutor", next_handler=None):
        super().__init__(next_handler)
        self.executor = executor
    
    def can_handle(self, response: str, context: "ExecutionContext") -> bool:
        return "[命令]" in response
    
    def process(self, response: str, context: "ExecutionContext") -> HandlerResult:
        commands = InputParser.extract_commands(response)
        if not commands:
            return HandlerResult.RETRY

        if len(commands) == 1:
            command = commands[0]
            print(f"[执行命令]: {command}")
            result = self.executor.execute(command)
        else:
            result = self._execute_many(commands)

        if not result.success:
            print(f"[执行错误]: {result.feedback}\n")
            context.metadata['last_error'] = result.feedback
            context.metadata['command_failure_count'] = (
                context.metadata.get('command_failure_count', 0) + 1
            )
        else:
            print(f"[执行结果]:\n{result.feedback}\n")
            context.metadata['last_output'] = result.feedback
            context.metadata['command_failure_count'] = 0

        # 保存命令和结果到上下文
        context.last_command = "\n\n".join(commands)
        context.metadata['execution_result'] = result
        
        return HandlerResult.CONTINUE

    def _execute_many(self, commands: list[str]):
        outputs: list[str] = [f"检测到 {len(commands)} 条命令，已按顺序执行。"]
        for index, command in enumerate(commands, start=1):
            print(f"[执行命令 {index}/{len(commands)}]: {command}")
            result = self.executor.execute(command)
            outputs.append(f"[{index}/{len(commands)}] {command}\n{result.feedback}")
            if not result.success:
                return type(result)(
                    output="",
                    return_code=result.return_code,
                    is_timeout=result.is_timeout,
                    error="\n\n".join(outputs),
                )
        return type(result)(
            output="\n\n".join(outputs),
            return_code=0,
        )
