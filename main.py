#!/usr/bin/env python3
"""Agent 应用主入口"""
import getpass
import sys
from pathlib import Path

from config import ConfigManager
from core import AgentOrchestrator, ContextCompressor, ConversationManager
from services import LLMClient, CommandExecutor
from skills import SkillRegistry


def _print_skill_help():
    """打印 CLI 技能管理命令"""
    print(
        "技能命令:\n"
        "  /skills                  列出当前技能\n"
        "  /reload-skills           重新扫描技能目录\n"
        "  /add-skill <name> [内容]  添加技能；省略内容时进入多行输入，单独输入 . 结束\n"
    )


def _print_config_help():
    """打印 CLI 配置管理命令"""
    print(
        "配置命令:\n"
        "  /config                         查看当前 API URL、模型和脱敏 API KEY\n"
        "  /config set api_key             隐藏输入并保存 API KEY\n"
        "  /config set api_key <value>     保存 API KEY\n"
        "  /config set base_url <url>      保存 API URL\n"
        "  /config set model <name>        保存模型名称\n"
    )


def _print_config(config: ConfigManager):
    """脱敏打印当前 LLM 配置"""
    public_config = config.get_public_llm_config()
    print(
        "当前 LLM 配置:\n"
        f"  API URL: {public_config['base_url']}\n"
        f"  API KEY: {public_config['api_key_masked'] or '<未设置>'}\n"
        f"  模型: {public_config['model']}\n"
        f"  配置文件: {public_config['config_file']}"
    )


def _read_multiline_skill_content(skill_name: str) -> str:
    """读取多行技能内容"""
    print(f"输入 {skill_name} 技能内容，单独输入 . 结束：")
    lines = []
    while True:
        line = input()
        if line == ".":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _new_llm_client(config: ConfigManager) -> LLMClient:
    """按当前配置创建 LLM 客户端"""
    return LLMClient(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        timeout=config["timeout"],
    )


def _resolve_project_path(project_root: Path, value: str) -> Path:
    """解析相对项目根目录的配置路径。"""
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _append_file_generation_prompt(agent_prompt: str, project_root: Path, generated_dir: Path) -> str:
    """把统一文件生成目录注入系统提示词。"""
    return agent_prompt + (
        "\n\n## 文件生成目录\n\n"
        f"- 当前命令工作目录固定为：{generated_dir}\n"
        "- 所有新建、导出、下载、转换、保存的文件都必须写入当前工作目录，"
        "也就是 GENERATED_FILES_DIR/FILES_DIR 指向的目录。\n"
        "- 生成文件时直接使用文件名或子目录名，不要再额外加 files/ 前缀。\n"
        f"- 如需读取或检查项目源码，使用 PROJECT_ROOT 环境变量：{project_root}\n"
        "- 完成时请给出生成文件相对该目录的文件名。\n"
    )


def _handle_config_command(
    user_input: str,
    config: ConfigManager,
    orchestrator: AgentOrchestrator,
    context_compressor: ContextCompressor,
) -> bool:
    """处理 CLI 配置管理命令，返回是否已处理"""
    stripped = user_input.strip()
    if stripped == "/config-help":
        _print_config_help()
        return True

    if stripped == "/config":
        _print_config(config)
        return True

    if not stripped.startswith("/config set"):
        return False

    parts = stripped.split(maxsplit=3)
    if len(parts) < 3:
        _print_config_help()
        return True

    field = parts[2]
    value = parts[3].strip() if len(parts) > 3 else ""
    update_kwargs = {}

    if field == "api_key":
        if not value:
            value = getpass.getpass("API KEY: ").strip()
        update_kwargs["api_key"] = value
    elif field == "base_url":
        update_kwargs["base_url"] = value
    elif field == "model":
        update_kwargs["model"] = value
    else:
        print("未知配置项，可用项: api_key, base_url, model")
        return True

    try:
        config.update_llm_config(**update_kwargs)
    except ValueError as e:
        print(f"配置错误: {e}")
        return True

    old_client = orchestrator.llm_client
    new_client = _new_llm_client(config)
    orchestrator.llm_client = new_client
    context_compressor.llm_client = new_client
    old_client.close()
    print("配置已保存，后续请求将使用新配置")
    _print_config(config)
    return True


def _handle_skill_command(user_input: str, skill_registry: SkillRegistry) -> bool:
    """处理 CLI 技能管理命令，返回是否已处理"""
    stripped = user_input.strip()
    if stripped in {"/skill-help", "/skills-help"}:
        _print_skill_help()
        return True
    
    if stripped == "/skills":
        skills = skill_registry.list_skills()
        if skills:
            print("当前技能: " + ", ".join(skills))
        else:
            print("当前没有可用技能")
        return True
    
    if stripped == "/reload-skills":
        skills = skill_registry.reload()
        print(f"已重载技能，共 {len(skills)} 个: {', '.join(skills) if skills else '无'}")
        return True
    
    if stripped.startswith("/add-skill"):
        parts = stripped.split(maxsplit=2)
        if len(parts) < 2:
            print("用法: /add-skill <name> [内容]")
            return True
        
        skill_name = parts[1]
        content = parts[2].strip() if len(parts) > 2 else _read_multiline_skill_content(skill_name)
        try:
            skill_registry.create_skill(skill_name, content)
        except FileExistsError:
            print(f"[警告] 技能已存在：{skill_name}")
        except ValueError as e:
            print(f"[警告] {e}")
        else:
            print(f"[添加技能]: {skill_name}")
        return True
    
    return False


def main():
    """主函数"""
    try:
        # 加载配置
        config = ConfigManager()
        project_root = Path(__file__).resolve().parent
        generated_dir = _resolve_project_path(project_root, config["generated_files_dir"])
        
        # 加载 Agent 提示词
        agent_path = _resolve_project_path(project_root, config["agent_file"])
        agent_prompt = agent_path.read_text(encoding='utf-8')
        agent_prompt = _append_file_generation_prompt(
            agent_prompt,
            project_root,
            generated_dir,
        )
        
        # 初始化组件
        llm_client = _new_llm_client(config)
        
        conversation = ConversationManager(agent_prompt)
        context_compressor = ContextCompressor(
            llm_client=llm_client,
            max_context_chars=config["context_max_chars"],
            recent_messages=config["context_recent_messages"],
            summary_target_chars=config["summary_target_chars"],
            summary_input_chars=config["summary_input_chars"],
        )
        skills_dir = _resolve_project_path(project_root, config["skills_dir"])
        skill_registry = SkillRegistry(str(skills_dir))
        executor = CommandExecutor(
            timeout=config["timeout"],
            cwd=generated_dir,
            generated_files_dir=generated_dir,
        )
        
        # 创建编排器
        orchestrator = AgentOrchestrator(
            llm_client=llm_client,
            conversation=conversation,
            skill_registry=skill_registry,
            executor=executor,
            context_compressor=context_compressor,
        )
        
        print("Agent 已启动，输入 Ctrl+C 退出；输入 /skill-help 或 /config-help 查看命令\n")
        
        # 主循环
        try:
            while True:
                try:
                    user_input = input("User: ")
                    if _handle_config_command(user_input, config, orchestrator, context_compressor):
                        continue
                    if _handle_skill_command(user_input, skill_registry):
                        continue
                    orchestrator.process_user_input(user_input)
                except KeyboardInterrupt:
                    print("\n已退出")
                    break
        finally:
            orchestrator.llm_client.close()
    
    except ValueError as e:
        print(f"配置错误: {e}")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"文件错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"未知错误: {e}")
        raise


if __name__ == "__main__":
    main()
