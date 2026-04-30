"""输入解析器"""
import re
from typing import Optional, Tuple


class InputParser:
    """解析用户输入"""
    
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
