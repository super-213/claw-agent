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
    HOME_ASSISTANT_ENV_KEYS = {
        "base_url": "HOME_ASSISTANT_URL",
        "token": "HOME_ASSISTANT_TOKEN",
        "allowed_entities": "HOME_ASSISTANT_ALLOWED_ENTITIES",
        "request_timeout": "HOME_ASSISTANT_REQUEST_TIMEOUT",
    }
    
    DEFAULT_CONFIG = {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "agent_file": "Agent.md",
        "skills_dir": "skills",
        "conversation_dir": ".data/conversations",
        "user_file": ".data/users.json",
        "generated_files_dir": "files",
        "timeout": 30,
        "max_retries": 3,
        "context_max_chars": 60000,
        "context_recent_messages": 12,
        "summary_target_chars": 6000,
        "summary_input_chars": 30000,
        "token_encoding": "cl100k_base",
        "home_data_dir": ".data/home",
        "home_timezone": "Asia/Shanghai",
        "home_scheduler_interval_seconds": 60,
        "home_notification_quiet_start": "22:00",
        "home_notification_quiet_end": "07:00",
        "home_backup_retention_days": 30,
        "home_assistant_url": "",
        "home_assistant_token": "",
        "home_assistant_allowed_entities": "",
        "home_assistant_request_timeout": 10,
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

        if user_file := os.getenv("USER_FILE"):
            config["user_file"] = user_file

        if generated_files_dir := os.getenv("GENERATED_FILES_DIR"):
            config["generated_files_dir"] = generated_files_dir

        if token_encoding := os.getenv("TOKEN_ENCODING"):
            config["token_encoding"] = token_encoding

        if home_data_dir := os.getenv("HOME_DATA_DIR"):
            config["home_data_dir"] = home_data_dir

        if home_timezone := os.getenv("HOME_TIMEZONE"):
            config["home_timezone"] = home_timezone

        if quiet_start := os.getenv("HOME_NOTIFICATION_QUIET_START"):
            config["home_notification_quiet_start"] = quiet_start

        if quiet_end := os.getenv("HOME_NOTIFICATION_QUIET_END"):
            config["home_notification_quiet_end"] = quiet_end

        if home_assistant_url := os.getenv("HOME_ASSISTANT_URL"):
            config["home_assistant_url"] = home_assistant_url.rstrip("/")

        if home_assistant_token := os.getenv("HOME_ASSISTANT_TOKEN"):
            config["home_assistant_token"] = home_assistant_token

        if home_assistant_allowed_entities := os.getenv("HOME_ASSISTANT_ALLOWED_ENTITIES"):
            config["home_assistant_allowed_entities"] = home_assistant_allowed_entities

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
            "HOME_SCHEDULER_INTERVAL_SECONDS": "home_scheduler_interval_seconds",
            "HOME_BACKUP_RETENTION_DAYS": "home_backup_retention_days",
            "HOME_ASSISTANT_REQUEST_TIMEOUT": "home_assistant_request_timeout",
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
            "home_assistant": self.get_public_home_assistant_config(),
        }

    def get_public_home_assistant_config(self) -> Dict[str, Any]:
        """返回可展示的 Home Assistant 配置，不泄露完整 Token"""
        token = self.config.get("home_assistant_token", "")
        allowed_entities = self.config.get("home_assistant_allowed_entities", "")
        return {
            "base_url": self.config.get("home_assistant_url", ""),
            "token_set": bool(token),
            "token_masked": self.mask_secret(token),
            "allowed_entities": allowed_entities,
            "allowed_entity_count": len([
                item for item in str(allowed_entities).replace("\n", ",").split(",")
                if item.strip()
            ]),
            "request_timeout": self.config.get("home_assistant_request_timeout", 10),
            "configured": bool(self.config.get("home_assistant_url") and token),
            "config_file": str(self._target_dotenv_path()),
            "env_names": self.HOME_ASSISTANT_ENV_KEYS.copy(),
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

    def update_home_assistant_config(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        allowed_entities: str | None = None,
        request_timeout: int | None = None,
    ) -> Dict[str, Any]:
        """更新 Home Assistant 配置并写入 .env；token 为空时保留原值"""
        updates: Dict[str, Any] = {}

        if base_url is not None:
            stripped_url = base_url.strip()
            updates["home_assistant_url"] = self._validate_optional_base_url("Home Assistant URL", stripped_url)
        if token is not None and token.strip():
            updates["home_assistant_token"] = self._validate_secret("Home Assistant Token", token.strip())
        if allowed_entities is not None:
            updates["home_assistant_allowed_entities"] = self._validate_allowed_entities(allowed_entities)
        if request_timeout is not None:
            try:
                timeout = int(request_timeout)
            except (TypeError, ValueError) as exc:
                raise ValueError("Home Assistant 请求超时必须是数字") from exc
            if timeout < 1 or timeout > 120:
                raise ValueError("Home Assistant 请求超时必须在 1 到 120 秒之间")
            updates["home_assistant_request_timeout"] = timeout

        if not updates:
            return self.get_public_home_assistant_config()

        env_updates = {}
        key_map = {
            "home_assistant_url": "HOME_ASSISTANT_URL",
            "home_assistant_token": "HOME_ASSISTANT_TOKEN",
            "home_assistant_allowed_entities": "HOME_ASSISTANT_ALLOWED_ENTITIES",
            "home_assistant_request_timeout": "HOME_ASSISTANT_REQUEST_TIMEOUT",
        }
        for key, value in updates.items():
            env_updates[key_map[key]] = str(value).replace("\n", ",")

        self._write_dotenv_values(self._target_dotenv_path(), env_updates)

        for env_name, value in env_updates.items():
            os.environ[env_name] = value

        self.config.update(updates)
        return self.get_public_home_assistant_config()

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

    def _validate_optional_base_url(self, label: str, value: str) -> str:
        if not value:
            return ""
        value = self._validate_plain_value(label, value, max_length=512)
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{label} 必须是有效的 http(s) 地址")
        return value.rstrip("/")

    def _validate_allowed_entities(self, value: str) -> str:
        cleaned = []
        for item in str(value or "").replace("\n", ",").split(","):
            item = item.strip()
            if not item:
                continue
            if len(item) > 240:
                raise ValueError("Home Assistant 白名单条目过长")
            if any(char in item for char in ("\r", "\x00")):
                raise ValueError("Home Assistant 白名单不能包含控制字符")
            entity_id = item.split("|", 1)[0].strip()
            if "." not in entity_id:
                raise ValueError(f"Home Assistant Entity ID 无效: {entity_id}")
            domain, name = entity_id.split(".", 1)
            allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
            if not domain or not name or any(char not in allowed_chars for char in domain + name):
                raise ValueError(f"Home Assistant Entity ID 无效: {entity_id}")
            cleaned.append(item)
        return "\n".join(cleaned)

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
