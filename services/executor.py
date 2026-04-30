"""命令执行器"""
import subprocess
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionResult:
    """命令执行结果"""
    output: str
    return_code: int
    is_timeout: bool = False
    error: Optional[str] = None
    
    @property
    def success(self) -> bool:
        return self.return_code == 0 and not self.is_timeout
    
    @classmethod
    def timeout(cls):
        return cls(output="", return_code=-1, is_timeout=True, error="命令执行超时")


class CommandExecutor:
    """安全的命令执行器"""
    
    # 危险命令模式
    DANGEROUS_PATTERNS = [
        r'rm\s+-rf\s+/',
        r'mkfs',
        r'dd\s+if=',
        r':\(\)\{.*\}',  # Fork bomb
        r'chmod\s+-R\s+777',
    ]
    
    # 交互式命令（不支持）
    INTERACTIVE_COMMANDS = ['vi', 'vim', 'nano', 'python', 'python3', 'node', 'irb']
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
    
    def execute(self, command: str) -> ExecutionResult:
        """执行命令"""
        # 清理命令
        command = self._clean_command(command)
        
        # 安全检查
        if error := self._validate_command(command):
            return ExecutionResult(output="", return_code=-1, error=error)
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            output = result.stdout if result.stdout else result.stderr
            return ExecutionResult(output=output, return_code=result.returncode)
        
        except subprocess.TimeoutExpired:
            return ExecutionResult.timeout()
        
        except Exception as e:
            return ExecutionResult(output="", return_code=-1, error=str(e))
    
    def _clean_command(self, command: str) -> str:
        """清理命令字符串"""
        # 移除代码块标记
        command = command.replace('```', '').replace('`', '').strip()
        return command
    
    def _validate_command(self, command: str) -> Optional[str]:
        """验证命令安全性"""
        # 检查危险模式
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return f"拒绝执行危险命令: {command}"
        
        # 检查交互式命令
        cmd_parts = command.split()
        if cmd_parts and cmd_parts[0] in self.INTERACTIVE_COMMANDS:
            return f"不支持交互式命令: {cmd_parts[0]}"
        
        return None
