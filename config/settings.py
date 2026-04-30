"""配置管理器"""
import os
from pathlib import Path
from typing import Dict, Any
from urllib.parse import urlparse

from dotenv import load_dotenv


class ConfigManager:
    """统一配置管理"""

    LLM_ENV_KEYS = {
        "api_key": "DASHSCOPE_API_KEY",
        "base_url": "API_BASE_URL",
        "model": "MODEL_NAME",
    }
    
    DEFAULT_CONFIG = {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "agent_file": "Agent.md",
        "skills_dir": "skills",
        "conversation_dir": ".data/conversations",
        "timeout": 30,
        "max_retries": 3,
        "context_max_chars": 60000,
        "context_recent_messages": 12,
        "summary_target_chars": 6000,
        "summary_input_chars": 30000,
        "token_encoding": "cl100k_base",
    }
    
    def __init__(self, config_path: str = None):
        self.project_root = Path(__file__).resolve().parents[1]
        self.dotenv_paths = self._get_dotenv_paths(config_path)
        self.config = self._load_config(config_path)
        self._validate()

    def _get_dotenv_paths(self, config_path: str = None) -> list[Path]:
        """获取候选 .env 路径"""
        if config_path:
            return [Path(config_path)]

        project_root = Path(__file__).resolve().parents[1]
        return [
            project_root / ".env",
            project_root / "config" / ".env",
        ]
    
    def _load_config(self, config_path: str = None) -> Dict[str, Any]:
        """加载配置：环境变量 > 配置文件 > 默认值"""
        config = self.DEFAULT_CONFIG.copy()

        # 读取 .env（不覆盖已存在的环境变量）
        for dotenv_path in self.dotenv_paths:
            if dotenv_path.exists():
                load_dotenv(dotenv_path=dotenv_path, override=False)
        
        # 从环境变量加载
        if api_key := os.getenv("DASHSCOPE_API_KEY"):
            config["api_key"] = api_key
        
        if base_url := os.getenv("API_BASE_URL"):
            config["base_url"] = base_url
        
        if model := os.getenv("MODEL_NAME"):
            config["model"] = model

        if agent_file := os.getenv("AGENT_FILE"):
            config["agent_file"] = agent_file

        if skills_dir := os.getenv("SKILLS_DIR"):
            config["skills_dir"] = skills_dir

        if conversation_dir := os.getenv("CONVERSATION_DIR"):
            config["conversation_dir"] = conversation_dir

        if token_encoding := os.getenv("TOKEN_ENCODING"):
            config["token_encoding"] = token_encoding

        if timeout := os.getenv("TIMEOUT"):
            try:
                config["timeout"] = int(timeout)
            except ValueError:
                pass

        if max_retries := os.getenv("MAX_RETRIES"):
            try:
                config["max_retries"] = int(max_retries)
            except ValueError:
                pass

        int_envs = {
            "CONTEXT_MAX_CHARS": "context_max_chars",
            "CONTEXT_RECENT_MESSAGES": "context_recent_messages",
            "SUMMARY_TARGET_CHARS": "summary_target_chars",
            "SUMMARY_INPUT_CHARS": "summary_input_chars",
        }
        for env_name, config_key in int_envs.items():
            if value := os.getenv(env_name):
                try:
                    config[config_key] = int(value)
                except ValueError:
                    pass
        
        return config
    
    def _validate(self):
        """验证配置"""
        if not self.config.get("api_key"):
            raise ValueError("未设置 DASHSCOPE_API_KEY 环境变量")
        
        agent_file = Path(self.config["agent_file"])
        if not agent_file.exists():
            raise FileNotFoundError(f"Agent 文件不存在: {agent_file}")
    
    def get(self, key: str, default=None):
        """获取配置项"""
        return self.config.get(key, default)
    
    def __getitem__(self, key: str):
        return self.config[key]

    def get_public_llm_config(self) -> Dict[str, Any]:
        """返回可展示的 LLM 配置，不泄露完整 API KEY"""
        api_key = self.config.get("api_key", "")
        return {
            "base_url": self.config.get("base_url", ""),
            "model": self.config.get("model", ""),
            "api_key_set": bool(api_key),
            "api_key_masked": self.mask_secret(api_key),
            "config_file": str(self._target_dotenv_path()),
            "env_names": self.LLM_ENV_KEYS.copy(),
        }

    def update_llm_config(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> Dict[str, Any]:
        """更新 LLM 配置并写入 .env；api_key 为 None 或空字符串时保留原值"""
        updates: Dict[str, str] = {}

        if api_key is not None and api_key.strip():
            updates["api_key"] = self._validate_secret("API KEY", api_key.strip())
        if base_url is not None:
            updates["base_url"] = self._validate_base_url(base_url.strip())
        if model is not None:
            updates["model"] = self._validate_plain_value("模型名称", model.strip())

        if not updates:
            return self.get_public_llm_config()

        new_config = self.config.copy()
        new_config.update(updates)
        if not new_config.get("api_key"):
            raise ValueError("未设置 DASHSCOPE_API_KEY 环境变量")

        env_updates = {
            self.LLM_ENV_KEYS[key]: value
            for key, value in updates.items()
        }
        self._write_dotenv_values(self._target_dotenv_path(), env_updates)

        for env_name, value in env_updates.items():
            os.environ[env_name] = value

        self.config.update(updates)
        self._validate()
        return self.get_public_llm_config()

    @staticmethod
    def mask_secret(value: str) -> str:
        """脱敏展示密钥"""
        if not value:
            return ""
        if len(value) <= 10:
            return "*" * len(value)
        return f"{value[:6]}...{value[-4:]}"

    def _target_dotenv_path(self) -> Path:
        """选择写入的 .env；优先写已有且优先级最高的文件"""
        for dotenv_path in self.dotenv_paths:
            if dotenv_path.exists():
                return dotenv_path
        return self.project_root / "config" / ".env"

    def _validate_secret(self, label: str, value: str) -> str:
        if not value:
            raise ValueError(f"{label} 不能为空")
        return self._validate_plain_value(label, value, max_length=512)

    def _validate_plain_value(self, label: str, value: str, max_length: int = 200) -> str:
        if not value:
            raise ValueError(f"{label} 不能为空")
        if len(value) > max_length:
            raise ValueError(f"{label} 过长")
        if any(char in value for char in ("\n", "\r", "\x00")):
            raise ValueError(f"{label} 不能包含换行或控制字符")
        return value

    def _validate_base_url(self, value: str) -> str:
        value = self._validate_plain_value("API URL", value, max_length=512)
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API URL 必须是有效的 http(s) 地址")
        return value.rstrip("/")

    def _write_dotenv_values(self, dotenv_path: Path, values: Dict[str, str]):
        """安全写入 .env，保留其他配置和注释"""
        dotenv_path.parent.mkdir(parents=True, exist_ok=True)
        existing_lines = dotenv_path.read_text(encoding="utf-8").splitlines() if dotenv_path.exists() else []
        pending = values.copy()
        output_lines = []

        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                output_lines.append(line)
                continue

            key = line.split("=", 1)[0].strip()
            if key in pending:
                output_lines.append(f"{key}={pending.pop(key)}")
            else:
                output_lines.append(line)

        if pending and output_lines and output_lines[-1].strip():
            output_lines.append("")
        for key, value in pending.items():
            output_lines.append(f"{key}={value}")

        tmp_path = dotenv_path.with_name(f".{dotenv_path.name}.tmp")
        tmp_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
        tmp_path.replace(dotenv_path)
        try:
            os.chmod(dotenv_path, 0o600)
        except OSError:
            pass
