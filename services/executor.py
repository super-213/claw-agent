"""命令执行器"""
import os
import subprocess
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
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

    @property
    def feedback(self) -> str:
        """返回给模型看的执行反馈，避免失败时丢失 stderr。"""
        if self.success:
            return self.output or "命令执行成功，无输出"
        details = self.error or self.output or "命令执行失败，无输出"
        return f"命令执行失败，退出码 {self.return_code}: {details}"
    
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
    SINGLE_DEST_COMMANDS = {"cp", "mv"}
    MULTI_PATH_WRITE_COMMANDS = {"touch", "mkdir"}
    REDIRECT_OPERATORS = {">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>"}
    
    def __init__(
        self,
        timeout: int = 30,
        cwd: str | Path | None = None,
        generated_files_dir: str | Path | None = None,
    ):
        self.timeout = timeout
        self.cwd = Path(cwd).resolve() if cwd else None
        self.generated_files_dir = (
            Path(generated_files_dir).resolve()
            if generated_files_dir
            else self.cwd
        )
        if self.cwd:
            self.cwd.mkdir(parents=True, exist_ok=True)
        if self.generated_files_dir:
            self.generated_files_dir.mkdir(parents=True, exist_ok=True)
    
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
                timeout=self.timeout,
                cwd=str(self.cwd) if self.cwd else None,
                env=self._command_env(),
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

        if error := self._validate_write_targets(command):
            return error
        
        return None

    def _validate_write_targets(self, command: str) -> Optional[str]:
        """禁止把生成文件写到统一目录之外的绝对路径。"""
        if not self.generated_files_dir:
            return None

        try:
            tokens = shlex.split(command, posix=True)
        except ValueError as exc:
            return f"命令解析失败: {exc}"

        for index, token in enumerate(tokens):
            if token in self.REDIRECT_OPERATORS and index + 1 < len(tokens):
                if error := self._validate_output_path(tokens[index + 1]):
                    return error

        for segment in self._split_shell_segments(tokens):
            if not segment:
                continue
            program = Path(segment[0]).name
            if program in self.SINGLE_DEST_COMMANDS:
                path_args = self._path_args(segment[1:])
                if path_args:
                    if error := self._validate_output_path(path_args[-1]):
                        return error
            elif program in self.MULTI_PATH_WRITE_COMMANDS:
                for path_arg in self._path_args(segment[1:]):
                    if error := self._validate_output_path(path_arg):
                        return error

        return None

    def _split_shell_segments(self, tokens: list[str]) -> list[list[str]]:
        segments: list[list[str]] = []
        current: list[str] = []
        for token in tokens:
            if token in {"&&", "||", ";", "|"}:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(token)
        if current:
            segments.append(current)
        return segments

    def _path_args(self, args: list[str]) -> list[str]:
        path_args: list[str] = []
        skip_next = False
        for arg in args:
            if skip_next:
                skip_next = False
                continue
            if arg == "--":
                continue
            if arg in {"-o", "-O", "-d", "-t"}:
                skip_next = True
                continue
            if arg.startswith("-"):
                continue
            path_args.append(arg)
        return path_args

    def _validate_output_path(self, raw_path: str) -> Optional[str]:
        expanded = os.path.expandvars(os.path.expanduser(raw_path))
        path = Path(expanded)
        if not path.is_absolute():
            return None

        try:
            path.resolve().relative_to(self.generated_files_dir)
        except ValueError:
            return (
                "拒绝写入固定生成目录之外的路径: "
                f"{raw_path}。请把文件保存到 {self.generated_files_dir}，"
                "命令中直接使用文件名或 $GENERATED_FILES_DIR/文件名。"
            )
        return None

    def _command_env(self) -> dict[str, str]:
        """为模型命令提供稳定的目录环境变量。"""
        env = os.environ.copy()
        if self.cwd:
            env["AGENT_WORK_DIR"] = str(self.cwd)
        if self.generated_files_dir:
            env["GENERATED_FILES_DIR"] = str(self.generated_files_dir)
            env["FILES_DIR"] = str(self.generated_files_dir)
        project_root = Path(__file__).resolve().parents[1]
        env["PROJECT_ROOT"] = str(project_root)
        return env
