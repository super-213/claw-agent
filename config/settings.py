"""配置管理器"""
import os
from pathlib import Path
from typing import Dict, Any

from dotenv import load_dotenv


class ConfigManager:
    """统一配置管理"""
    
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
        self.config = self._load_config(config_path)
        self._validate()
    
    def _load_config(self, config_path: str = None) -> Dict[str, Any]:
        """加载配置：环境变量 > 配置文件 > 默认值"""
        config = self.DEFAULT_CONFIG.copy()

        # 读取 .env（不覆盖已存在的环境变量）
        project_root = Path(__file__).resolve().parents[1]
        dotenv_paths = [
            project_root / ".env",
            project_root / "config" / ".env",
        ]
        for dotenv_path in dotenv_paths:
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
