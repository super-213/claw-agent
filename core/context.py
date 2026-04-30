"""执行上下文"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExecutionContext:
    """执行上下文，用于在处理器之间传递状态"""
    
    active_skill: Optional[str] = None
    should_continue: bool = True
    last_command: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    
    def reset_skill(self):
        """重置技能状态"""
        self.active_skill = None
    
    def activate_skill(self, skill_name: str):
        """激活技能"""
        self.active_skill = skill_name
    
    def stop(self):
        """停止执行"""
        self.should_continue = False
