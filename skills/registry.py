"""技能注册表"""
from pathlib import Path
from typing import Dict, Optional
from .base import BaseSkill


class MarkdownSkill(BaseSkill):
    """基于 Markdown 文件的技能"""
    
    def __init__(self, name: str, file_path: Path):
        super().__init__(name)
        self.file_path = file_path
    
    def load_context(self) -> str:
        """加载 Markdown 文件内容"""
        return self.file_path.read_text(encoding='utf-8')


class SkillRegistry:
    """技能注册表"""
    
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self._skills: Dict[str, BaseSkill] = {}
        self._discover_skills()
    
    def _discover_skills(self):
        """自动发现技能"""
        if not self.skills_dir.exists():
            return
        
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            
            skill_name = skill_dir.name
            skill_file = skill_dir / f"{skill_name}.md"
            
            if skill_file.exists():
                skill = MarkdownSkill(skill_name, skill_file)
                self.register(skill)
    
    def register(self, skill: BaseSkill):
        """注册技能"""
        self._skills[skill.name] = skill
    
    def get(self, name: str) -> Optional[BaseSkill]:
        """获取技能"""
        return self._skills.get(name)
    
    def list_skills(self) -> list:
        """列出所有技能"""
        return list(self._skills.keys())
    
    def has_skill(self, name: str) -> bool:
        """检查技能是否存在"""
        return name in self._skills
