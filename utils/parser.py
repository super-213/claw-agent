"""输入解析器"""
import re
from typing import Optional, Tuple


class InputParser:
    """解析用户输入"""
    COMMAND_MARKER = "[命令]"

    # 实时查询意图关键词
    REALTIME_KEYWORDS = [
        r"今天", r"现在", r"最新", r"当前", r"实时", r"目前",
        r"最近", r"今年", r"本月", r"这周",
        r"天气", r"气温", r"股价", r"汇率", r"比分",
        r"新闻", r"热搜", r"发布了", r"更新了",
        r"多少钱", r"价格", r"费用",
        r"帮我[查搜找]", r"搜[一索]", r"查[一询]下",
        r"latest", r"current", r"today", r"now",
    ]
    _REALTIME_PATTERN = re.compile("|".join(REALTIME_KEYWORDS), re.I)

    @staticmethod
    def needs_realtime_search(text: str) -> bool:
        """检测用户输入是否包含实时查询意图"""
        return bool(InputParser._REALTIME_PATTERN.search(text))
    
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
        """提取模型回复中的第一条命令，支持 heredoc 多行写入命令。"""
        commands = InputParser.extract_commands(text)
        return commands[0] if commands else ""

    @staticmethod
    def extract_commands(text: str) -> list[str]:
        """提取模型回复中的全部命令。

        模型偶尔会违反提示词一次输出多条 [命令]。这里顺序提取，避免只执行
        第一条后让模型误以为后续文件也已写入。
        """
        if InputParser.COMMAND_MARKER not in text:
            return []

        commands: list[str] = []
        for raw in text.split(InputParser.COMMAND_MARKER)[1:]:
            command = InputParser._extract_command_from_marker_body(raw)
            if command:
                commands.append(command)
        return commands

    @staticmethod
    def _extract_command_from_marker_body(raw: str) -> str:
        raw = raw.strip()
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
