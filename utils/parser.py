"""输入解析器"""
import re
from typing import Optional, Tuple


class InputParser:
    """解析用户输入"""
    COMMAND_MARKER = "[命令]"
    
    @staticmethod
    def extract_skill_call(text: str) -> Optional[str]:
        """提取 '调用 XXX skill' 中的 XXX"""
        match = re.search(r'调用\s+(\S+)\s+skill', text, re.I)
        return match.group(1).strip() if match else None
    
    @staticmethod
    def remove_skill_call(text: str) -> str:
        """移除技能调用部分"""
        return re.sub(r'调用\s+\S+\s+skill\s*', '', text, flags=re.I).strip()
    
    @staticmethod
    def parse_user_input(text: str) -> Tuple[Optional[str], str]:
        """解析用户输入，返回 (技能名, 清理后的文本)"""
        skill_name = InputParser.extract_skill_call(text)
        if skill_name:
            text = InputParser.remove_skill_call(text)
        return skill_name, text

    @staticmethod
    def extract_command(text: str) -> str:
        """提取模型回复中的命令，支持 heredoc 多行写入命令。"""
        if InputParser.COMMAND_MARKER not in text:
            return ""

        raw = text.split(InputParser.COMMAND_MARKER, 1)[1].strip()
        if not raw:
            return ""

        raw = InputParser._unwrap_fenced_command(raw)
        lines = raw.splitlines()
        if not lines:
            return ""

        first_line = lines[0].strip()
        delimiter = InputParser._heredoc_delimiter(first_line)
        if not delimiter:
            return first_line

        command_lines = [lines[0]]
        for line in lines[1:]:
            command_lines.append(line)
            if line.strip() == delimiter:
                break
        return "\n".join(command_lines).strip()

    @staticmethod
    def _unwrap_fenced_command(text: str) -> str:
        lines = text.splitlines()
        if not lines or not lines[0].strip().startswith("```"):
            return text

        command_lines: list[str] = []
        for line in lines[1:]:
            if line.strip().startswith("```"):
                break
            command_lines.append(line)
        return "\n".join(command_lines).strip()

    @staticmethod
    def _heredoc_delimiter(command_line: str) -> Optional[str]:
        match = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", command_line)
        return match.group(2) if match else None
