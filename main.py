#!/usr/bin/env python3
"""Agent 应用主入口"""
import sys
from pathlib import Path

from config import ConfigManager
from core import AgentOrchestrator, ContextCompressor, ConversationManager
from services import LLMClient, CommandExecutor
from skills import SkillRegistry


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
        
        print("Agent 已启动，输入 Ctrl+C 退出\n")
        
        # 主循环
        with llm_client:
            while True:
                try:
                    user_input = input("User: ")
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
