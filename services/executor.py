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
    
    # 交互式命令（不支持）。python/node 允许带 -c/-m/脚本等一次性执行形式。
    ALWAYS_INTERACTIVE_COMMANDS = {"vi", "vim", "nano", "irb"}
    REPL_CAPABLE_COMMANDS = {"python", "python3", "node"}
    PYTHON_EXEC_FLAGS = {"-c", "-m"}
    PYTHON_EXIT_FLAGS = {
        "-V",
        "--version",
        "-h",
        "--help",
        "--help-env",
        "--help-xoptions",
        "--help-all",
    }
    NODE_EXEC_FLAGS = {"-e", "--eval", "-p", "--print", "-c", "--check"}
    NODE_EXIT_FLAGS = {"-v", "--version", "-h", "--help"}
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
            before_files = self._file_snapshot()
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
            execution_result = ExecutionResult(output=output, return_code=result.returncode)
            if execution_result.success:
                if error := self._validate_generated_outputs(command, before_files):
                    return ExecutionResult(output=output, return_code=-1, error=error)
            return execution_result
        
        except subprocess.TimeoutExpired:
            return ExecutionResult.timeout()
        
        except Exception as e:
            return ExecutionResult(output="", return_code=-1, error=str(e))
    
    def _clean_command(self, command: str) -> str:
        """清理命令字符串"""
        command = command.strip()
        lines = command.splitlines()
        if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip().startswith("```"):
            return "\n".join(lines[1:-1]).strip()
        return command
    
    def _validate_command(self, command: str) -> Optional[str]:
        """验证命令安全性"""
        # 检查危险模式
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return f"拒绝执行危险命令: {command}"
        
        command_for_validation = self._strip_heredoc_bodies(command)
        try:
            tokens = shlex.split(command_for_validation, posix=True)
        except ValueError as exc:
            return f"命令解析失败: {exc}"

        if error := self._validate_interactive_commands(tokens):
            return error

        if error := self._validate_write_targets(tokens):
            return error
        
        return None

    def _strip_heredoc_bodies(self, command: str) -> str:
        """校验命令时跳过 heredoc 正文，避免正文内容被 shlex 当作 shell 语法解析。"""
        lines = command.splitlines()
        if not lines:
            return command

        stripped_lines: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped_lines.append(line)
            delimiters = self._heredoc_delimiters(line)
            index += 1
            for delimiter in delimiters:
                while index < len(lines) and lines[index].strip() != delimiter:
                    index += 1
                if index < len(lines):
                    index += 1
        return "\n".join(stripped_lines)

    def _heredoc_delimiters(self, command_line: str) -> list[str]:
        matches = re.finditer(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", command_line)
        return [match.group(2) for match in matches]

    def _validate_interactive_commands(self, tokens: list[str]) -> Optional[str]:
        """拦截会等待用户输入的 REPL/编辑器，允许一次性脚本命令。"""
        for segment in self._split_shell_segments(tokens):
            if not segment:
                continue
            program = Path(segment[0]).name
            if program in self.ALWAYS_INTERACTIVE_COMMANDS:
                return f"不支持交互式命令: {program}"
            if program in self.REPL_CAPABLE_COMMANDS and self._starts_repl(program, segment[1:]):
                return f"不支持交互式命令: {program}"
        return None

    def _starts_repl(self, program: str, args: list[str]) -> bool:
        if not args:
            return True
        if program in {"python", "python3"}:
            return self._python_starts_repl(args)
        if program == "node":
            return self._node_starts_repl(args)
        return False

    def _python_starts_repl(self, args: list[str]) -> bool:
        for index, arg in enumerate(args):
            if arg == "-i":
                return True
            if arg in self.PYTHON_EXEC_FLAGS:
                return False
            if arg in self.PYTHON_EXIT_FLAGS:
                return False
            if arg == "-":
                return False
            if arg == "--":
                return index + 1 >= len(args)
            if not arg.startswith("-"):
                return False
        return True

    def _node_starts_repl(self, args: list[str]) -> bool:
        for index, arg in enumerate(args):
            if arg == "-i" or arg == "--interactive":
                return True
            if arg in self.NODE_EXEC_FLAGS:
                return False
            if arg in self.NODE_EXIT_FLAGS:
                return False
            if arg == "-":
                return False
            if arg == "--":
                return index + 1 >= len(args)
            if not arg.startswith("-"):
                return False
        return True

    def _validate_write_targets(self, tokens: list[str]) -> Optional[str]:
        """禁止把生成文件写到统一目录之外的绝对路径。"""
        if not self.generated_files_dir:
            return None

        for raw_path in self._redirect_output_paths(tokens):
            if error := self._validate_output_path(raw_path):
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

    def _validate_generated_outputs(
        self,
        command: str,
        before_files: dict[Path, tuple[int, int]],
    ) -> Optional[str]:
        """对可识别的重定向输出做基本完整性检查。"""
        command_for_validation = self._strip_heredoc_bodies(command)
        try:
            tokens = shlex.split(command_for_validation, posix=True)
        except ValueError:
            tokens = []

        paths = set(self._changed_generated_files(before_files))
        for raw_path in self._redirect_output_paths(tokens):
            paths.add(self._resolve_output_path(raw_path))

        for path in sorted(paths):
            if error := self._validate_generated_file(path):
                return error
        return None

    def _file_snapshot(self) -> dict[Path, tuple[int, int]]:
        if not self.generated_files_dir or not self.generated_files_dir.exists():
            return {}

        snapshot: dict[Path, tuple[int, int]] = {}
        for path in self.generated_files_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[path.resolve()] = (stat.st_mtime_ns, stat.st_size)
        return snapshot

    def _changed_generated_files(self, before_files: dict[Path, tuple[int, int]]) -> list[Path]:
        if not self.generated_files_dir or not self.generated_files_dir.exists():
            return []

        changed: list[Path] = []
        for path in self.generated_files_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                resolved = path.resolve()
                stat = path.stat()
            except OSError:
                continue
            current = (stat.st_mtime_ns, stat.st_size)
            if before_files.get(resolved) != current:
                changed.append(resolved)
        return changed

    def _validate_generated_file(self, path: Path) -> Optional[str]:
        if not path.exists() or not path.is_file():
            return None
        if path.name.startswith("."):
            return None

        size = path.stat().st_size
        if size == 0:
            return f"文件写入失败: {path} 为 0 字节，可能被截断"
        if path.suffix.lower() == ".pdf":
            with path.open("rb") as file:
                header = file.read(5)
            if header != b"%PDF-":
                return f"PDF 写入失败: {path} 缺少 %PDF- 文件头，可能被截断或编码错误"
        return None

    def _redirect_output_paths(self, tokens: list[str]) -> list[str]:
        paths: list[str] = []
        for index, token in enumerate(tokens):
            if token in self.REDIRECT_OPERATORS and index + 1 < len(tokens):
                paths.append(tokens[index + 1])
        return paths

    def _resolve_output_path(self, raw_path: str) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(raw_path))
        path = Path(expanded)
        if path.is_absolute():
            return path.resolve()
        base_dir = self.cwd if self.cwd else Path.cwd()
        return (base_dir / path).resolve()

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
