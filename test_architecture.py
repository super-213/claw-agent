#!/usr/bin/env python3
"""架构测试脚本 - 验证各模块是否正常工作"""
import sys
from pathlib import Path

# 添加当前目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))


def test_imports():
    """测试所有模块导入"""
    print("测试模块导入...")
    try:
        from config import ConfigManager
        from core import ConversationManager, ExecutionContext
        from services import CommandExecutor, ExecutionResult
        from skills import BaseSkill, SkillRegistry, MarkdownSkill
        from handlers import ResponseHandler, HandlerResult, CompletionHandler, SkillOutputHandler
        from utils import InputParser
        print("✅ 所有模块导入成功")
        return True
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config():
    """测试配置管理"""
    print("\n测试配置管理...")
    try:
        import os
        os.environ['DASHSCOPE_API_KEY'] = 'test_key'
        
        from config import ConfigManager
        config = ConfigManager()
        
        assert config.get('api_key') == 'test_key'
        assert config['model'] == 'qwen-plus'
        print("✅ 配置管理正常")
        return True
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
        return False


def test_config_update_security():
    """测试 LLM 配置更新不会明文返回 API KEY"""
    print("\n测试 LLM 配置安全更新...")
    import os
    from tempfile import TemporaryDirectory

    env_names = ["DASHSCOPE_API_KEY", "API_BASE_URL", "MODEL_NAME"]
    original_env = {name: os.environ.get(name) for name in env_names}
    for name in env_names:
        os.environ.pop(name, None)

    try:
        from config import ConfigManager

        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join([
                    "DASHSCOPE_API_KEY=old-secret-key",
                    "API_BASE_URL=https://old.example.com/v1",
                    "MODEL_NAME=old-model",
                    "TIMEOUT=45",
                ]) + "\n",
                encoding="utf-8",
            )

            config = ConfigManager(str(env_path))
            public_config = config.get_public_llm_config()
            assert public_config["api_key_set"] is True
            assert "old-secret-key" not in str(public_config)
            assert public_config["api_key_masked"] == "old-se...-key"

            config.update_llm_config(
                base_url="https://new.example.com/v1/",
                model="new-model",
            )
            text = env_path.read_text(encoding="utf-8")
            assert "DASHSCOPE_API_KEY=old-secret-key" in text
            assert "API_BASE_URL=https://new.example.com/v1" in text
            assert "MODEL_NAME=new-model" in text
            assert config["base_url"] == "https://new.example.com/v1"

            updated = config.update_llm_config(api_key="new-secret-key-1234")
            assert "new-secret-key-1234" not in str(updated)
            assert "DASHSCOPE_API_KEY=new-secret-key-1234" in env_path.read_text(encoding="utf-8")

        print("✅ LLM 配置安全更新正常")
        return True
    except Exception as e:
        print(f"❌ LLM 配置安全更新失败: {e}")
        return False
    finally:
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_conversation():
    """测试对话管理"""
    print("\n测试对话管理...")
    try:
        from core import ConversationManager
        
        conv = ConversationManager("System prompt")
        conv.add_user_message("Hello")
        conv.add_assistant_message("Hi")
        
        messages = conv.get_messages()
        assert len(messages) == 3  # system + user + assistant
        assert messages[1]['role'] == 'user'
        conv.set_summary("历史摘要", 2)
        assert conv.get_summary() == "历史摘要"
        assert conv.get_summarized_until() == 2
        print("✅ 对话管理正常")
        return True
    except Exception as e:
        print(f"❌ 对话管理测试失败: {e}")
        return False


def test_context_compressor():
    """测试上下文压缩"""
    print("\n测试上下文压缩...")
    try:
        from core import ConversationManager, ContextCompressor

        class FakeLLMClient:
            def __init__(self):
                self.calls = 0

            def chat(self, messages):
                self.calls += 1
                return "压缩后的历史摘要"

        conv = ConversationManager("System prompt")
        for idx in range(10):
            conv.add_user_message(f"用户消息 {idx} " + "x" * 80)
            conv.add_assistant_message(f"助手回复 {idx} " + "y" * 80)

        fake_client = FakeLLMClient()
        compressor = ContextCompressor(
            llm_client=fake_client,
            max_context_chars=800,
            recent_messages=4,
            summary_target_chars=200,
            summary_input_chars=500,
        )
        prompt_messages = compressor.build_messages(conv)

        assert fake_client.calls > 0
        assert conv.get_summary() == "压缩后的历史摘要"
        assert conv.get_summarized_until() > 1
        assert prompt_messages[0]["role"] == "system"
        assert "历史对话摘要" in prompt_messages[1]["content"]
        assert prompt_messages[-1]["content"].startswith("助手回复 9")

        print("✅ 上下文压缩正常")
        return True
    except Exception as e:
        print(f"❌ 上下文压缩测试失败: {e}")
        return False


def test_conversation_store_summary():
    """测试对话摘要持久化"""
    print("\n测试对话摘要持久化...")
    try:
        from tempfile import TemporaryDirectory
        from services import ConversationStore

        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session = store.create_session("System prompt")
            session_id = session["id"]
            messages = [
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ]
            store.save_messages(
                session_id,
                messages,
                summary="摘要内容",
                summarized_until=2,
            )
            loaded = store.load_session(session_id)

        assert loaded["summary"] == "摘要内容"
        assert loaded["summarized_until"] == 2
        assert len(loaded["messages"]) == 3
        assert loaded["token_usage"]["total_tokens"] > 0
        assert loaded["messages"][1]["usage"]["category"] == "user"

        print("✅ 对话摘要持久化正常")
        return True
    except Exception as e:
        print(f"❌ 对话摘要持久化测试失败: {e}")
        return False


def test_token_usage_estimator():
    """测试 token 用量估算"""
    print("\n测试 token 用量估算...")
    try:
        from services import TokenUsageEstimator

        estimator = TokenUsageEstimator()
        messages = estimator.annotate_messages([
            {"role": "system", "content": "System prompt"},
            {"role": "assistant", "content": "[命令] pwd"},
            {"role": "user", "content": "[执行完成]\n/tmp"},
        ])
        totals = estimator.summarize_session(messages)

        assert messages[0]["usage"]["category"] == "system_prompt"
        assert messages[1]["usage"]["category"] == "tool_call"
        assert messages[2]["usage"]["category"] == "tool_result"
        assert totals["tool_tokens"] == (
            messages[1]["usage"]["total_tokens"]
            + messages[2]["usage"]["total_tokens"]
        )
        assert totals["total_tokens"] >= totals["tool_tokens"]

        print("✅ token 用量估算正常")
        return True
    except Exception as e:
        print(f"❌ token 用量估算测试失败: {e}")
        return False


def test_skill_registry():
    """测试技能注册表"""
    print("\n测试技能注册表...")
    try:
        import tempfile
        from pathlib import Path
        from skills import SkillRegistry
        
        registry = SkillRegistry("skills")
        skills = registry.list_skills()
        
        if 'calculator' in skills:
            calc_skill = registry.get('calculator')
            content = calc_skill.load_context()
            assert 'calculator' in content.lower()
            print(f"✅ 技能注册表正常，发现 {len(skills)} 个技能: {skills}")
        else:
            print("⚠️  未发现 calculator 技能，但注册表功能正常")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_registry = SkillRegistry(temp_dir)
            created = temp_registry.create_skill("demo", "# demo\n测试技能")
            assert created.name == "demo"
            assert temp_registry.has_skill("demo")
            assert "测试技能" in temp_registry.get("demo").load_context()
            
            external_dir = Path(temp_dir) / "external"
            external_dir.mkdir()
            (external_dir / "external.md").write_text("# external\n热重载技能", encoding="utf-8")
            assert "external" in temp_registry.list_skills()
            assert "热重载技能" in temp_registry.get("external").load_context()
        
        return True
    except Exception as e:
        print(f"❌ 技能注册表测试失败: {e}")
        return False


def test_executor():
    """测试命令执行器"""
    print("\n测试命令执行器...")
    try:
        from services import CommandExecutor
        
        executor = CommandExecutor(timeout=5)
        
        # 测试安全命令
        result = executor.execute("echo 'test'")
        assert result.success
        assert 'test' in result.output
        
        # 测试危险命令拦截
        result = executor.execute("rm -rf /")
        assert not result.success
        assert result.error is not None
        
        print("✅ 命令执行器正常（包括安全检查）")
        return True
    except Exception as e:
        print(f"❌ 命令执行器测试失败: {e}")
        return False


def test_parser():
    """测试输入解析器"""
    print("\n测试输入解析器...")
    try:
        from utils import InputParser
        
        # 测试技能提取
        skill, text = InputParser.parse_user_input("调用 calculator skill 计算 2+3")
        assert skill == 'calculator'
        assert '计算 2+3' in text
        
        # 测试普通输入
        skill, text = InputParser.parse_user_input("查看当前目录")
        assert skill is None
        assert text == "查看当前目录"
        
        print("✅ 输入解析器正常")
        return True
    except Exception as e:
        print(f"❌ 输入解析器测试失败: {e}")
        return False


def test_handlers():
    """测试处理器链"""
    print("\n测试处理器链...")
    try:
        from handlers import CompletionHandler, HandlerResult
        from core import ExecutionContext
        
        handler = CompletionHandler()
        context = ExecutionContext()
        
        # 测试完成标记
        result = handler.handle("[完成] 任务完成", context)
        assert result == HandlerResult.BREAK
        assert not context.should_continue
        
        print("✅ 处理器链正常")
        return True
    except Exception as e:
        print(f"❌ 处理器链测试失败: {e}")
        return False


def main():
    """运行所有测试"""
    print("=" * 50)
    print("架构重构验证测试")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_config,
        test_config_update_security,
        test_conversation,
        test_context_compressor,
        test_conversation_store_summary,
        test_token_usage_estimator,
        test_skill_registry,
        test_executor,
        test_parser,
        test_handlers,
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)
    print(f"测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！架构重构成功！")
        return 0
    else:
        print("⚠️  部分测试失败，请检查")
        return 1


if __name__ == "__main__":
    sys.exit(main())
