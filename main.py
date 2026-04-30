#!/usr/bin/env python3
"""Agent 应用主入口"""
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
        
        # 加载 Agent 提示词
        agent_prompt = Path(config["agent_file"]).read_text(encoding='utf-8')
        
        # 初始化组件
        llm_client = LLMClient(
            api_key=config["api_key"],
            base_url=config["base_url"],
            model=config["model"],
            timeout=config["timeout"]
        )
        
        conversation = ConversationManager(agent_prompt)
        context_compressor = ContextCompressor(
            llm_client=llm_client,
            max_context_chars=config["context_max_chars"],
            recent_messages=config["context_recent_messages"],
            summary_target_chars=config["summary_target_chars"],
            summary_input_chars=config["summary_input_chars"],
        )
        skill_registry = SkillRegistry(config["skills_dir"])
        executor = CommandExecutor(timeout=config["timeout"])
        
        # 创建编排器
        orchestrator = AgentOrchestrator(
            llm_client=llm_client,
            conversation=conversation,
            skill_registry=skill_registry,
            executor=executor,
            context_compressor=context_compressor,
        )
        
        print("Agent 已启动，输入 Ctrl+C 退出；输入 /skill-help 查看技能命令\n")
        
        # 主循环
        with llm_client:
            while True:
                try:
                    user_input = input("User: ")
                    if _handle_skill_command(user_input, skill_registry):
                        continue
                    orchestrator.process_user_input(user_input)
                except KeyboardInterrupt:
                    print("\n已退出")
                    break
    
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
