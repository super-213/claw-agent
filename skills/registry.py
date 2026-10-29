"""技能注册表"""
from pathlib import Path
from dataclasses import dataclass, field
import json
import re
import yaml
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple
from .base import BaseSkill


@dataclass(frozen=True)
class SkillManifest:
    name: str
    description: str = ""
    triggers: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    allowed_tools_list: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    version: str = "1.0.0"
    allow_auto: bool = True
    parameters_schema: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, fallback_name: str) -> "SkillManifest":
        def strings(key: str) -> tuple[str, ...]:
            value = payload.get(key) or []
            return tuple(str(item) for item in value if str(item).strip()) if isinstance(value, list) else ()
        return cls(
            name=str(payload.get("name") or fallback_name),
            description=str(payload.get("description") or ""),
            triggers=strings("triggers"),
            required_tools=strings("required_tools"),
            allowed_tools_list=strings("allowed_tools"),
            permissions=strings("permissions"),
            resources=strings("resources"),
            version=str(payload.get("version") or "1.0.0"),
            allow_auto=payload.get("allow_auto", True) is True,
            parameters_schema=dict(payload.get("parameters_schema") or {}),
        )


class MarkdownSkill(BaseSkill):
    """基于文本文件的技能"""
    
    def __init__(self, name: str, file_path: Path, manifest: SkillManifest | None = None):
        super().__init__(name)
        self.file_path = file_path
        self.root_dir = file_path.parent
        self.manifest = manifest or SkillManifest(name=name)
    
    def load_context(self) -> str:
        """加载技能文件内容"""
        return self.file_path.read_text(encoding='utf-8')

    def summary(self) -> str:
        description = self.manifest.description.strip()
        if not description:
            for line in self.load_context().splitlines():
                cleaned = line.strip().lstrip("#").strip()
                if cleaned:
                    description = cleaned
                    break
        return f"{self.name}: {description or self.name} (v{self.manifest.version})"

    def allowed_tools(self) -> Optional[set[str]]:
        values = self.manifest.allowed_tools_list
        return set(values) if values else None


class SkillRegistry:
    """技能注册表"""
    
    _VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
    SUPPORTED_SUFFIXES: Tuple[str, ...] = (".md", ".skill")
    
    def __init__(self, skills_dir: str = "skills", auto_reload: bool = True):
        self.skills_dir = Path(skills_dir)
        self._skills: Dict[str, BaseSkill] = {}
        self._errors: Dict[str, str] = {}
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
        return [
            skill_dir / "SKILL.md",
            *[skill_dir / f"{skill_name}{suffix}" for suffix in self.SUPPORTED_SUFFIXES],
        ]

    def _load_manifest(self, skill_dir: Path, skill_name: str) -> SkillManifest:
        path = skill_dir / "manifest.json"
        tools_path = skill_dir / "tools.json"
        if not path.exists():
            payload: dict[str, Any] = {"name": skill_name}
            source = next((p for p in self._skill_files(skill_dir, skill_name) if p.is_file()), None)
            text = source.read_text(encoding="utf-8") if source else ""
            header = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
            if header:
                try:
                    metadata = yaml.safe_load(header.group(1))
                except yaml.YAMLError as exc:
                    raise ValueError(f"技能 {skill_name} frontmatter 无效") from exc
                if isinstance(metadata, dict) and isinstance(metadata.get("description"), str):
                    payload["description"] = metadata["description"]
                # Foreign frontmatter is descriptive data, never a grant of tools/permissions.
        else:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"技能 {skill_name} manifest 无效: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"技能 {skill_name} manifest 必须是对象")
        try:
            tools_payload = json.loads(tools_path.read_text(encoding="utf-8")) if tools_path.exists() else None
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"技能 {skill_name} tools.json 无效: {exc}") from exc
        if isinstance(tools_payload, list):
            payload.setdefault("allowed_tools", tools_payload)
        elif isinstance(tools_payload, dict):
            payload.setdefault("allowed_tools", tools_payload.get("allowed_tools") or [])
            payload.setdefault("required_tools", tools_payload.get("required_tools") or [])
        manifest = SkillManifest.from_payload(payload, fallback_name=skill_name)
        if manifest.name != skill_name:
            raise ValueError(f"技能目录名与 manifest.name 不一致: {skill_name}")
        return manifest
    
    def _discover_skills(self) -> Dict[str, BaseSkill]:
        """自动发现技能"""
        discovered: Dict[str, BaseSkill] = {}
        self._errors = {}
        if not self.skills_dir.exists():
            return discovered
        
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.name.startswith(".") or not skill_dir.is_dir():
                continue
            
            skill_name = skill_dir.name
            for skill_file in self._skill_files(skill_dir, skill_name):
                if skill_file.exists():
                    try:
                        manifest = self._load_manifest(skill_dir, skill_name)
                    except ValueError as exc:
                        self._errors[skill_name] = str(exc)
                        break
                    discovered[skill_name] = MarkdownSkill(skill_name, skill_file, manifest)
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
        explicit_legacy_suffix = any((name or "").strip().endswith(suffix) for suffix in self.SUPPORTED_SUFFIXES)
        skill_name, suffix = self._parse_skill_name(name)
        skill_content = (content or "").strip()
        if not skill_content:
            raise ValueError("技能内容不能为空")
        
        skill_dir = self.skills_dir / skill_name
        skill_file = (
            skill_dir / f"{skill_name}{suffix}"
            if explicit_legacy_suffix
            else skill_dir / "SKILL.md"
        )
        
        with self._lock:
            if any(path.exists() for path in self._skill_files(skill_dir, skill_name)):
                raise FileExistsError(f"技能已存在：{skill_name}")
            
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(skill_content + "\n", encoding="utf-8")
            manifest = SkillManifest(
                name=skill_name,
                description=next(
                    (line.strip().lstrip("#").strip() for line in skill_content.splitlines() if line.strip()),
                    skill_name,
                ),
            )
            if not explicit_legacy_suffix:
                (skill_dir / "manifest.json").write_text(
                    json.dumps({
                        "name": manifest.name,
                        "description": manifest.description,
                        "version": manifest.version,
                        "triggers": [],
                        "required_tools": [],
                        "allowed_tools": [],
                        "permissions": [],
                        "resources": [],
                        "allow_auto": True,
                        "parameters_schema": {},
                    }, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            skill = MarkdownSkill(skill_name, skill_file, manifest)
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

    def catalog(self, *, auto_only: bool = False) -> List[Dict[str, Any]]:
        self._reload_if_needed()
        rows = []
        for name in sorted(self._skills):
            skill = self._skills[name]
            manifest = getattr(skill, "manifest", SkillManifest(name=name))
            if auto_only and not manifest.allow_auto:
                continue
            rows.append({
                "name": name,
                "summary": skill.summary(),
                "triggers": list(manifest.triggers),
                "version": manifest.version,
                "allow_auto": manifest.allow_auto,
                "required_tools": list(manifest.required_tools),
            })
        return rows

    def load_for_runtime(
        self,
        name: str,
        *,
        available_tools: set[str] | None = None,
        automatic: bool = True,
    ) -> Dict[str, Any]:
        skill = self.get(name)
        if skill is None:
            raise KeyError("unknown_skill")
        manifest = getattr(skill, "manifest", SkillManifest(name=name))
        if automatic and not manifest.allow_auto:
            raise PermissionError("skill_requires_explicit_user_request")
        missing = set(manifest.required_tools) - set(available_tools or set())
        if missing:
            raise RuntimeError(f"skill_missing_required_tools:{','.join(sorted(missing))}")
        return {
            "name": name,
            "instructions": skill.load_context(),
            "allowed_tools": sorted(skill.allowed_tools() or []),
            "permissions": list(manifest.permissions),
            "version": manifest.version,
        }
    
    def has_skill(self, name: str) -> bool:
        """检查技能是否存在"""
        self._reload_if_needed()
        return name in self._skills

    def errors(self) -> Dict[str, str]:
        self._reload_if_needed()
        return dict(self._errors)
