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
        print("✅ 对话管理正常")
        return True
    except Exception as e:
        print(f"❌ 对话管理测试失败: {e}")
        return False


def test_skill_registry():
    """测试技能注册表"""
    print("\n测试技能注册表...")
    try:
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
        test_conversation,
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
