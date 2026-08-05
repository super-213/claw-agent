"""Agent run context."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionContext:
    """Small in-memory state for the currently executing Agent run."""
    
    active_skill: Optional[str] = None
    should_continue: bool = True
    
    def reset_skill(self):
        """重置技能状态"""
        self.active_skill = None
    
    def activate_skill(self, skill_name: str):
        """激活技能"""
        self.active_skill = skill_name
    
    def stop(self):
        """停止执行"""
        self.should_continue = False
