"""测试历史会话文件（无 node_id）加载时自动迁移且功能正常。

验证向后兼容性：
1. 旧格式文件（消息无 node_id）加载成功
2. 加载后所有消息都有 node_id 和 parent_id
3. active_node_id 设置为最后一条消息
4. 迁移后的会话功能正常（可创建分支、切换等）
"""
import json
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from core.branch_engine import BranchEngine
from core.conversation import ConversationManager
from services.conversation_store import ConversationStore


class TestOldFormatMigrationViaStore:
    """通过 ConversationStore.load_session() 测试旧格式自动迁移。"""

    def _create_old_format_session(self, store: ConversationStore) -> str:
        """创建一个不含 node_id 的旧格式会话文件，返回 session_id。"""
        session_id = uuid.uuid4().hex
        old_session = {
            "id": session_id,
            "title": "旧格式会话",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:01:00Z",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant.", "ts": "2024-01-01T00:00:00Z"},
                {"role": "user", "content": "Hello!", "ts": "2024-01-01T00:00:10Z"},
                {"role": "assistant", "content": "Hi there! How can I help?", "ts": "2024-01-01T00:00:15Z"},
                {"role": "user", "content": "What is Python?", "ts": "2024-01-01T00:00:30Z"},
                {"role": "assistant", "content": "Python is a programming language.", "ts": "2024-01-01T00:00:35Z"},
            ],
            "summary": "",
            "summarized_until": 1,
        }
        # Write directly to bypass create_session (which adds node_id)
        path = store._path(session_id)
        path.write_text(json.dumps(old_session, ensure_ascii=False, indent=2), encoding="utf-8")
        return session_id

    def test_old_format_loads_successfully(self):
        """旧格式文件（无 node_id）可以成功加载。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            # Should not raise
            session = store.load_session(session_id)
            assert session is not None
            assert session["id"] == session_id

    def test_all_messages_have_node_id_after_load(self):
        """加载后所有消息都有 node_id 字段。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            for i, msg in enumerate(messages):
                assert "node_id" in msg, f"Message {i} missing node_id"
                assert msg["node_id"] is not None, f"Message {i} has None node_id"
                assert len(msg["node_id"]) > 0, f"Message {i} has empty node_id"

    def test_all_messages_have_parent_id_after_load(self):
        """加载后所有消息都有 parent_id 字段（第一条为 None，其余指向前一条）。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            # First message: parent_id is None (root)
            assert messages[0]["parent_id"] is None

            # Subsequent messages: parent_id points to previous message
            for i in range(1, len(messages)):
                assert messages[i]["parent_id"] == messages[i - 1]["node_id"], (
                    f"Message {i} parent_id should point to message {i-1}'s node_id"
                )

    def test_active_node_id_set_to_last_message(self):
        """加载后 active_node_id 设置为最后一条消息的 node_id。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            assert "active_node_id" in session
            assert session["active_node_id"] == messages[-1]["node_id"]

    def test_unique_node_ids_after_migration(self):
        """迁移后每条消息的 node_id 唯一。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            node_ids = [msg["node_id"] for msg in messages]
            assert len(node_ids) == len(set(node_ids)), "node_ids should be unique"

    def test_message_content_preserved_after_migration(self):
        """迁移后消息内容保持不变。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            expected_contents = [
                "You are a helpful assistant.",
                "Hello!",
                "Hi there! How can I help?",
                "What is Python?",
                "Python is a programming language.",
            ]
            actual_contents = [msg["content"] for msg in messages]
            assert actual_contents == expected_contents

    def test_message_roles_preserved_after_migration(self):
        """迁移后消息角色保持不变。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            expected_roles = ["system", "user", "assistant", "user", "assistant"]
            actual_roles = [msg["role"] for msg in messages]
            assert actual_roles == expected_roles

    def test_migrated_session_can_create_branch(self):
        """迁移后的会话可以正常创建分支。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            # Build a BranchEngine from the migrated messages
            engine = BranchEngine(messages)

            # Create a branch at the second message (first user message)
            branch_point_id = messages[1]["node_id"]
            new_branch_id = engine.create_branch(branch_point_id)

            assert new_branch_id is not None
            assert new_branch_id in engine._nodes
            assert engine._nodes[new_branch_id]["parent_id"] == branch_point_id

    def test_migrated_session_can_switch_branch(self):
        """迁移后的会话可以正常切换分支。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            engine = BranchEngine(messages)

            # Create a branch at message[1] (first user message)
            branch_point_id = messages[1]["node_id"]
            new_branch_id = engine.create_branch(branch_point_id)

            # Switch to the new branch
            path = engine.get_path_to_node(new_branch_id)
            assert len(path) == 3  # root -> user -> new_branch
            assert path[0]["node_id"] == messages[0]["node_id"]
            assert path[1]["node_id"] == messages[1]["node_id"]
            assert path[2]["node_id"] == new_branch_id

    def test_migrated_session_can_build_context(self):
        """迁移后的会话可以正常构建上下文。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            engine = BranchEngine(messages)
            leaf_id = messages[-1]["node_id"]

            context = engine.build_context(leaf_id)
            assert len(context) == 5
            assert context[0]["role"] == "system"
            assert context[-1]["content"] == "Python is a programming language."

    def test_migrated_session_can_append_message(self):
        """迁移后的会话可以正常追加消息。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            engine = BranchEngine(messages)
            leaf_id = messages[-1]["node_id"]

            # Append a new user message
            new_msg = {"role": "user", "content": "Tell me more about Python."}
            new_id = engine.append_message(leaf_id, new_msg)

            assert new_id is not None
            assert engine._nodes[new_id]["content"] == "Tell me more about Python."
            assert engine._nodes[new_id]["parent_id"] == leaf_id

            # Verify the path includes the new message
            path = engine.get_path_to_node(new_id)
            assert len(path) == 6
            assert path[-1]["content"] == "Tell me more about Python."

    def test_migrated_session_branch_isolation(self):
        """迁移后创建分支，两个分支的上下文互相隔离。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = self._create_old_format_session(store)

            session = store.load_session(session_id)
            messages = session["messages"]

            engine = BranchEngine(messages)

            # Create a branch at message[1] (first user message)
            branch_point_id = messages[1]["node_id"]
            new_branch_id = engine.create_branch(branch_point_id)

            # Append a message on the new branch
            branch_msg = {"role": "assistant", "content": "Branch reply"}
            branch_reply_id = engine.append_message(new_branch_id, branch_msg)

            # Context for original path should NOT include branch messages
            original_leaf = messages[-1]["node_id"]
            original_context = engine.build_context(original_leaf)
            original_contents = [msg["content"] for msg in original_context]
            assert "Branch reply" not in original_contents

            # Context for new branch should NOT include original path messages after branch point
            branch_context = engine.build_context(branch_reply_id)
            branch_contents = [msg["content"] for msg in branch_context]
            assert "Hi there! How can I help?" not in branch_contents
            assert "What is Python?" not in branch_contents
            assert "Python is a programming language." not in branch_contents
            # But should include the shared ancestor messages
            assert "You are a helpful assistant." in branch_contents
            assert "Hello!" in branch_contents
            assert "Branch reply" in branch_contents


class TestOldFormatMigrationViaConversationManager:
    """通过 ConversationManager.load_messages() 测试旧格式自动迁移。"""

    def test_load_old_format_messages(self):
        """ConversationManager 可以加载不含 node_id 的旧格式消息。"""
        old_messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        conv = ConversationManager("System prompt")
        conv.load_messages(old_messages)

        messages = conv.get_messages()
        assert len(messages) == 3

        # All messages should now have node_id
        for msg in messages:
            assert "node_id" in msg
            assert msg["node_id"] is not None

    def test_branch_engine_initialized_after_migration(self):
        """加载旧格式消息后 BranchEngine 被正确初始化。"""
        old_messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        conv = ConversationManager("System prompt")
        conv.load_messages(old_messages)

        assert conv.branch_engine is not None
        assert conv.active_node_id is not None

    def test_active_node_id_is_last_message(self):
        """加载旧格式消息后 active_node_id 为最后一条消息。"""
        old_messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        conv = ConversationManager("System prompt")
        conv.load_messages(old_messages)

        messages = conv.get_messages()
        assert conv.active_node_id == messages[-1]["node_id"]

    def test_can_create_branch_after_migration(self):
        """迁移后可以通过 ConversationManager 创建分支。"""
        old_messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        conv = ConversationManager("System prompt")
        conv.load_messages(old_messages)

        messages = conv.get_messages()
        branch_point_id = messages[1]["node_id"]  # First user message

        result = conv.create_branch(branch_point_id)
        assert "branch_node_id" in result
        assert "ancestor_path" in result
        assert len(result["ancestor_path"]) == 3  # root -> user -> new_branch

    def test_can_switch_branch_after_migration(self):
        """迁移后可以通过 ConversationManager 切换分支。"""
        old_messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "More question"},
            {"role": "assistant", "content": "More answer"},
        ]

        conv = ConversationManager("System prompt")
        conv.load_messages(old_messages)

        messages = conv.get_messages()
        # Switch to the second message (first user message)
        target_id = messages[1]["node_id"]
        path = conv.switch_branch(target_id)

        assert len(path) == 2  # root -> user
        assert conv.active_node_id == target_id

    def test_get_messages_returns_active_path(self):
        """迁移后 get_messages() 返回当前活跃路径的消息。"""
        old_messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "More question"},
            {"role": "assistant", "content": "More answer"},
        ]

        conv = ConversationManager("System prompt")
        conv.load_messages(old_messages)

        # Initially, active path is the full linear chain
        messages = conv.get_messages()
        assert len(messages) == 5

        # Switch to an earlier node
        target_id = messages[2]["node_id"]  # assistant "Hi there"
        conv.switch_branch(target_id)

        # Now get_messages should return only root -> user -> assistant
        messages_after_switch = conv.get_messages()
        assert len(messages_after_switch) == 3
        assert messages_after_switch[-1]["content"] == "Hi there"


class TestOldFormatWithAttachments:
    """测试带附件/图片的旧格式消息迁移。"""

    def test_attachments_preserved_after_migration(self):
        """迁移后附件信息保持不变。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = uuid.uuid4().hex
            old_session = {
                "id": session_id,
                "title": "带附件的旧会话",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:01:00Z",
                "messages": [
                    {"role": "system", "content": "System prompt", "ts": "2024-01-01T00:00:00Z"},
                    {
                        "role": "user",
                        "content": "See this file",
                        "ts": "2024-01-01T00:00:10Z",
                        "attachments": [{"name": "doc.pdf", "url": "/files/doc.pdf"}],
                        "images": [{"url": "/images/screenshot.png", "alt": "screenshot"}],
                    },
                    {"role": "assistant", "content": "I see the file.", "ts": "2024-01-01T00:00:15Z"},
                ],
                "summary": "",
                "summarized_until": 1,
            }
            path = store._path(session_id)
            path.write_text(json.dumps(old_session, ensure_ascii=False, indent=2), encoding="utf-8")

            session = store.load_session(session_id)
            messages = session["messages"]

            # All messages should have node_id
            for msg in messages:
                assert "node_id" in msg

            # Attachments and images should be preserved
            user_msg = messages[1]
            assert user_msg["attachments"] == [{"name": "doc.pdf", "url": "/files/doc.pdf"}]
            assert user_msg["images"] == [{"url": "/images/screenshot.png", "alt": "screenshot"}]


class TestMixedFormatHandling:
    """测试混合格式（部分消息有 node_id，部分没有）的处理。"""

    def test_partial_node_id_triggers_migration(self):
        """如果部分消息缺少 node_id，应触发迁移。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = uuid.uuid4().hex
            # Mixed: first message has node_id, rest don't
            mixed_session = {
                "id": session_id,
                "title": "混合格式会话",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:01:00Z",
                "messages": [
                    {"role": "system", "content": "System", "ts": "2024-01-01T00:00:00Z", "node_id": "existing-id", "parent_id": None},
                    {"role": "user", "content": "Hello", "ts": "2024-01-01T00:00:10Z"},
                    {"role": "assistant", "content": "Hi", "ts": "2024-01-01T00:00:15Z"},
                ],
                "summary": "",
                "summarized_until": 1,
            }
            path = store._path(session_id)
            path.write_text(json.dumps(mixed_session, ensure_ascii=False, indent=2), encoding="utf-8")

            session = store.load_session(session_id)
            messages = session["messages"]

            # All messages should have node_id after migration
            for msg in messages:
                assert "node_id" in msg
                assert msg["node_id"] is not None

            # The first message should preserve its existing node_id
            assert messages[0]["node_id"] == "existing-id"

            # active_node_id should be set
            assert "active_node_id" in session
            assert session["active_node_id"] == messages[-1]["node_id"]


class TestNewFormatNotMigrated:
    """测试新格式文件（已有 node_id）不会被重复迁移。"""

    def test_new_format_not_re_migrated(self):
        """已有 node_id 的新格式文件加载时不触发迁移。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            session_id = uuid.uuid4().hex
            new_session = {
                "id": session_id,
                "title": "新格式会话",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:01:00Z",
                "active_node_id": "n3",
                "messages": [
                    {"role": "system", "content": "System", "ts": "2024-01-01T00:00:00Z", "node_id": "n1", "parent_id": None},
                    {"role": "user", "content": "Hello", "ts": "2024-01-01T00:00:10Z", "node_id": "n2", "parent_id": "n1"},
                    {"role": "assistant", "content": "Hi", "ts": "2024-01-01T00:00:15Z", "node_id": "n3", "parent_id": "n2"},
                ],
                "summary": "",
                "summarized_until": 1,
            }
            path = store._path(session_id)
            path.write_text(json.dumps(new_session, ensure_ascii=False, indent=2), encoding="utf-8")

            session = store.load_session(session_id)
            messages = session["messages"]

            # node_ids should remain unchanged
            assert messages[0]["node_id"] == "n1"
            assert messages[1]["node_id"] == "n2"
            assert messages[2]["node_id"] == "n3"

            # parent_ids should remain unchanged
            assert messages[0]["parent_id"] is None
            assert messages[1]["parent_id"] == "n1"
            assert messages[2]["parent_id"] == "n2"

            # active_node_id should remain unchanged
            assert session["active_node_id"] == "n3"


class TestEndToEndMigrationWorkflow:
    """端到端测试：旧格式加载 → 迁移 → 操作 → 保存 → 重新加载。"""

    def test_full_workflow(self):
        """完整工作流：加载旧格式 → 创建分支 → 保存 → 重新加载验证。"""
        with TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)

            # 1. Create old format session
            session_id = uuid.uuid4().hex
            old_session = {
                "id": session_id,
                "title": "端到端测试",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:01:00Z",
                "messages": [
                    {"role": "system", "content": "System prompt", "ts": "2024-01-01T00:00:00Z"},
                    {"role": "user", "content": "Hello", "ts": "2024-01-01T00:00:10Z"},
                    {"role": "assistant", "content": "Hi there", "ts": "2024-01-01T00:00:15Z"},
                    {"role": "user", "content": "Question", "ts": "2024-01-01T00:00:30Z"},
                    {"role": "assistant", "content": "Answer", "ts": "2024-01-01T00:00:35Z"},
                ],
                "summary": "",
                "summarized_until": 1,
            }
            path = store._path(session_id)
            path.write_text(json.dumps(old_session, ensure_ascii=False, indent=2), encoding="utf-8")

            # 2. Load (triggers migration)
            session = store.load_session(session_id)
            messages = session["messages"]
            active_node_id = session["active_node_id"]

            # Verify migration happened
            assert all("node_id" in msg for msg in messages)
            assert active_node_id == messages[-1]["node_id"]

            # 3. Create a branch using BranchEngine
            engine = BranchEngine(messages)
            branch_point = messages[1]["node_id"]  # First user message
            new_branch_id = engine.create_branch(branch_point)

            # Append a message on the new branch
            new_msg = {"role": "user", "content": "Alternative question"}
            alt_id = engine.append_message(new_branch_id, new_msg)

            # 4. Save the modified messages
            all_messages = list(engine._nodes.values())
            store.save_messages(
                session_id,
                all_messages,
                active_node_id=alt_id,
            )

            # 5. Reload and verify
            reloaded = store.load_session(session_id)
            reloaded_messages = reloaded["messages"]

            # Should have 7 messages now (5 original + 1 branch placeholder + 1 new)
            assert len(reloaded_messages) == 7

            # All should have node_id
            for msg in reloaded_messages:
                assert "node_id" in msg

            # active_node_id should be the alternative question
            assert reloaded["active_node_id"] == alt_id

            # Rebuild engine and verify both paths work
            engine2 = BranchEngine(reloaded_messages)

            # Original path
            original_context = engine2.build_context(messages[-1]["node_id"])
            original_contents = [m["content"] for m in original_context]
            assert "Answer" in original_contents

            # New branch path
            branch_context = engine2.build_context(alt_id)
            branch_contents = [m["content"] for m in branch_context]
            assert "Alternative question" in branch_contents
            assert "Answer" not in branch_contents
