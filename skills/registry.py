"""技能注册表"""
from pathlib import Path
import re
from threading import RLock
from typing import Dict, List, Optional, Tuple
from .base import BaseSkill


class MarkdownSkill(BaseSkill):
    """基于文本文件的技能"""
    
    def __init__(self, name: str, file_path: Path):
        super().__init__(name)
        self.file_path = file_path
    
    def load_context(self) -> str:
        """加载技能文件内容"""
        return self.file_path.read_text(encoding='utf-8')


class SkillRegistry:
    """技能注册表"""
    
    _VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
    SUPPORTED_SUFFIXES: Tuple[str, ...] = (".md", ".skill")
    
    def __init__(self, skills_dir: str = "skills", auto_reload: bool = True):
        self.skills_dir = Path(skills_dir)
        self._skills: Dict[str, BaseSkill] = {}
        self.auto_reload = auto_reload
        self._lock = RLock()
        self.reload()
    
    def _parse_skill_name(self, name: str) -> Tuple[str, str]:
        """校验技能名，并解析可选的技能文件后缀"""
        raw_name = (name or "").strip()
        suffix = ".md"

        for supported_suffix in self.SUPPORTED_SUFFIXES:
            if raw_name.endswith(supported_suffix):
                raw_name = raw_name[: -len(supported_suffix)]
                suffix = supported_suffix
                break

        skill_name = raw_name.strip()
        if not skill_name:
            raise ValueError("技能名不能为空")
        if not self._VALID_NAME.fullmatch(skill_name):
            raise ValueError("技能名只能包含字母、数字、下划线和中划线")
        return skill_name, suffix

    def _validate_skill_name(self, name: str) -> str:
        """校验并规范化技能名"""
        skill_name, _ = self._parse_skill_name(name)
        return skill_name

    def _skill_files(self, skill_dir: Path, skill_name: str) -> List[Path]:
        """按优先级返回技能文件候选路径"""
        return [skill_dir / f"{skill_name}{suffix}" for suffix in self.SUPPORTED_SUFFIXES]
    
    def _discover_skills(self) -> Dict[str, BaseSkill]:
        """自动发现技能"""
        discovered: Dict[str, BaseSkill] = {}
        if not self.skills_dir.exists():
            return discovered
        
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            
            skill_name = skill_dir.name
            for skill_file in self._skill_files(skill_dir, skill_name):
                if skill_file.exists():
                    discovered[skill_name] = MarkdownSkill(skill_name, skill_file)
                    break
        
        return discovered
    
    def reload(self) -> List[str]:
        """重新扫描技能目录，支持运行时新增/删除技能"""
        with self._lock:
            self._skills = self._discover_skills()
            return self.list_skills(reload=False)
    
    def _reload_if_needed(self):
        """按需热重载技能注册表"""
        if self.auto_reload:
            self.reload()
    
    def register(self, skill: BaseSkill):
        """注册技能"""
        with self._lock:
            self._skills[skill.name] = skill
    
    def create_skill(self, name: str, content: str) -> BaseSkill:
        """创建技能文件并注册，默认使用 .md，也支持显式 .skill 后缀"""
        skill_name, suffix = self._parse_skill_name(name)
        skill_content = (content or "").strip()
        if not skill_content:
            raise ValueError("技能内容不能为空")
        
        skill_dir = self.skills_dir / skill_name
        skill_file = skill_dir / f"{skill_name}{suffix}"
        
        with self._lock:
            if any(path.exists() for path in self._skill_files(skill_dir, skill_name)):
                raise FileExistsError(f"技能已存在：{skill_name}")
            
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(skill_content + "\n", encoding="utf-8")
            skill = MarkdownSkill(skill_name, skill_file)
            self.register(skill)
            return skill
    
    def get(self, name: str) -> Optional[BaseSkill]:
        """获取技能"""
        self._reload_if_needed()
        return self._skills.get(name)
    
    def list_skills(self, reload: bool = True) -> list:
        """列出所有技能"""
        if reload:
            self._reload_if_needed()
        return sorted(self._skills.keys())
    
    def has_skill(self, name: str) -> bool:
        """检查技能是否存在"""
        self._reload_if_needed()
        return name in self._skills
