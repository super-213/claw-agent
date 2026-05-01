"""技能基类"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class BaseSkill(ABC):
    """技能抽象基类"""
    
    def __init__(self, name: str):
        self.name = name
    
    @abstractmethod
    def load_context(self) -> str:
        """加载技能上下文（通常是 .md 或 .skill 文件内容）"""
        pass
    
    def parse_output(self, text: str) -> Optional[Dict[str, Any]]:
        """解析技能输出（可选实现）"""
        return None
    
    def get_marker(self) -> Optional[str]:
        """获取技能标记（如 [计算]、[天气]）"""
        return None
