"""Property-based tests for BranchEngine using Hypothesis.

Tests the following correctness properties from the design document:
1. 路径完整性 (Path Integrity)
2. 分支创建保持树完整性 (Branch Creation Preserves Tree Integrity)
3. 上下文隔离 (Context Isolation)
4. 删除后树一致性 (Deletion Consistency)
5. 向后兼容迁移 Round-Trip (Migration Round-Trip)
"""

import uuid
from hypothesis import given, assume, settings, HealthCheck
from hypothesis import strategies as st

from core.branch_engine import BranchEngine


# ---------------------------------------------------------------------------
# Strategies: generate valid tree structures for property testing
# ---------------------------------------------------------------------------

@st.composite
def linear_messages(draw, min_size=1, max_size=20):
    """Generate a linear list of messages (no branching)."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    roles = ["system", "user", "assistant"]
    messages = []
    for i in range(n):
        role = roles[0] if i == 0 else roles[1 + (i - 1) % 2]
        content = draw(st.text(min_size=1, max_size=50))
        messages.append({"role": role, "content": content})
    return messages


@st.composite
def tree_messages(draw, min_nodes=2, max_nodes=30):
    """Generate a valid tree of messages with node_id/parent_id fields.

    Builds a tree by starting with a root node and then adding children
    to randomly chosen existing nodes.
    """
    n = draw(st.integers(min_value=min_nodes, max_value=max_nodes))
    roles = ["user", "assistant"]
    messages = []

    # Root node
    root_id = str(uuid.uuid4())
    messages.append({
        "node_id": root_id,
        "parent_id": None,
        "role": "system",
        "content": draw(st.text(min_size=1, max_size=50)),
    })

    node_ids = [root_id]

    for i in range(1, n):
        parent_idx = draw(st.integers(min_value=0, max_value=len(node_ids) - 1))
        parent_id = node_ids[parent_idx]
        node_id = str(uuid.uuid4())
        role = roles[i % 2]
        content = draw(st.text(min_size=1, max_size=50))

        messages.append({
            "node_id": node_id,
            "parent_id": parent_id,
            "role": role,
            "content": content,
        })
        node_ids.append(node_id)

    return messages


@st.composite
def tree_with_target(draw, min_nodes=2, max_nodes=30):
    """Generate a tree and pick a random node from it as target."""
    messages = draw(tree_messages(min_nodes=min_nodes, max_nodes=max_nodes))
    target_idx = draw(st.integers(min_value=0, max_value=len(messages) - 1))
    target_id = messages[target_idx]["node_id"]
    return messages, target_id


@st.composite
def tree_with_branch_point(draw, min_nodes=2, max_nodes=30):
    """Generate a tree and pick a random node as branch point."""
    messages = draw(tree_messages(min_nodes=min_nodes, max_nodes=max_nodes))
    bp_idx = draw(st.integers(min_value=0, max_value=len(messages) - 1))
    branch_point_id = messages[bp_idx]["node_id"]
    return messages, branch_point_id


@st.composite
def tree_with_deletable_node(draw, min_nodes=3, max_nodes=30):
    """Generate a tree and pick a non-root node that is NOT on the active path.

    Returns (messages, node_to_delete, active_node_id).
    """
    messages = draw(tree_messages(min_nodes=min_nodes, max_nodes=max_nodes))

    # Find root
    root_id = None
    for msg in messages:
        if msg["parent_id"] is None:
            root_id = msg["node_id"]
            break

    # Build parent map for path computation
    parent_map = {msg["node_id"]: msg["parent_id"] for msg in messages}
    all_ids = [msg["node_id"] for msg in messages]
    non_root_ids = [nid for nid in all_ids if parent_map[nid] is not None]

    assume(len(non_root_ids) >= 2)

    # Pick an active node (a leaf or any non-root node)
    active_idx = draw(st.integers(min_value=0, max_value=len(non_root_ids) - 1))
    active_node_id = non_root_ids[active_idx]

    # Compute active path
    active_path_ids = set()
    current = active_node_id
    while current is not None:
        active_path_ids.add(current)
        current = parent_map.get(current)

    # Find nodes NOT on active path and NOT root
    deletable = [nid for nid in non_root_ids if nid not in active_path_ids]
    assume(len(deletable) >= 1)

    delete_idx = draw(st.integers(min_value=0, max_value=len(deletable) - 1))
    node_to_delete = deletable[delete_idx]

    return messages, node_to_delete, active_node_id


# ---------------------------------------------------------------------------
# Property 1: 路径完整性 (Path Integrity)
# ---------------------------------------------------------------------------

class TestPathIntegrityProperty:
    """For any node N in the tree, get_path_to_node(N) satisfies:
    - First element's parent_id is None (root)
    - Last element's node_id equals N
    - Adjacent elements: path[i+1].parent_id == path[i].node_id
    """

    @given(data=tree_with_target())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_path_starts_at_root(self, data):
        messages, target_id = data
        engine = BranchEngine(messages)
        path = engine.get_path_to_node(target_id)

        assert path[0]["parent_id"] is None

    @given(data=tree_with_target())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_path_ends_at_target(self, data):
        messages, target_id = data
        engine = BranchEngine(messages)
        path = engine.get_path_to_node(target_id)

        assert path[-1]["node_id"] == target_id

    @given(data=tree_with_target())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_path_adjacency_linked(self, data):
        messages, target_id = data
        engine = BranchEngine(messages)
        path = engine.get_path_to_node(target_id)

        for i in range(len(path) - 1):
            assert path[i + 1]["parent_id"] == path[i]["node_id"]

    @given(data=tree_with_target())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_path_has_no_duplicates(self, data):
        messages, target_id = data
        engine = BranchEngine(messages)
        path = engine.get_path_to_node(target_id)

        node_ids = [n["node_id"] for n in path]
        assert len(node_ids) == len(set(node_ids))


# ---------------------------------------------------------------------------
# Property 2: 分支创建保持树完整性 (Branch Creation Invariant)
# ---------------------------------------------------------------------------

class TestBranchCreationInvariant:
    """Creating a branch preserves:
    - All existing nodes' node_id and parent_id unchanged
    - All existing paths still reachable
    - Branch point's child count increases by 1
    """

    @given(data=tree_with_branch_point())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_existing_nodes_unchanged(self, data):
        messages, branch_point_id = data
        engine = BranchEngine(messages)

        # Snapshot before
        nodes_before = {
            nid: (node["node_id"], node["parent_id"])
            for nid, node in engine._nodes.items()
        }

        engine.create_branch(branch_point_id)

        # All original nodes still have same node_id and parent_id
        for nid, (orig_node_id, orig_parent_id) in nodes_before.items():
            assert engine._nodes[nid]["node_id"] == orig_node_id
            assert engine._nodes[nid]["parent_id"] == orig_parent_id

    @given(data=tree_with_branch_point())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_existing_paths_still_reachable(self, data):
        messages, branch_point_id = data
        engine = BranchEngine(messages)

        # Collect all leaf nodes (nodes with no children)
        leaves_before = [
            nid for nid, children in engine._children.items()
            if len(children) == 0
        ]

        engine.create_branch(branch_point_id)

        # All original leaves are still reachable
        for leaf_id in leaves_before:
            path = engine.get_path_to_node(leaf_id)
            assert path[-1]["node_id"] == leaf_id

    @given(data=tree_with_branch_point())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_branch_point_child_count_increases_by_one(self, data):
        messages, branch_point_id = data
        engine = BranchEngine(messages)

        children_before = len(engine._children.get(branch_point_id, []))
        engine.create_branch(branch_point_id)
        children_after = len(engine._children.get(branch_point_id, []))

        assert children_after == children_before + 1

    @given(data=tree_with_branch_point())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_new_branch_node_path_ends_at_branch_point(self, data):
        messages, branch_point_id = data
        engine = BranchEngine(messages)

        new_id = engine.create_branch(branch_point_id)
        path = engine.get_path_to_node(new_id)

        # The second-to-last node should be the branch point
        assert path[-2]["node_id"] == branch_point_id
        assert path[-1]["node_id"] == new_id
        assert path[-1]["parent_id"] == branch_point_id


# ---------------------------------------------------------------------------
# Property 3: 上下文隔离 (Context Isolation)
# ---------------------------------------------------------------------------

class TestContextIsolationProperty:
    """For any active path P, build_context(P.leaf) returns messages that:
    - Are a subset of the root-to-leaf path
    - Do NOT contain any node from other branches
    """

    @given(data=tree_with_target())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_context_is_subset_of_path(self, data):
        messages, target_id = data
        engine = BranchEngine(messages)

        path = engine.get_path_to_node(target_id)
        context = engine.build_context(target_id)

        path_ids = {msg["node_id"] for msg in path}
        context_ids = {msg["node_id"] for msg in context}

        assert context_ids.issubset(path_ids)

    @given(data=tree_messages(min_nodes=4, max_nodes=30))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_context_excludes_other_branches(self, data):
        messages = data
        engine = BranchEngine(messages)

        # Find all leaf nodes
        all_ids = set(engine._nodes.keys())
        parent_ids = {
            msg["parent_id"] for msg in engine._nodes.values()
            if msg["parent_id"] is not None
        }
        leaves = all_ids - parent_ids

        assume(len(leaves) >= 2)

        # Pick two different leaves
        leaves_list = sorted(leaves)
        leaf_a = leaves_list[0]
        leaf_b = leaves_list[-1]
        assume(leaf_a != leaf_b)

        # Get paths
        path_a_ids = {msg["node_id"] for msg in engine.get_path_to_node(leaf_a)}
        context_b = engine.build_context(leaf_b)
        context_b_ids = {msg["node_id"] for msg in context_b}

        # Nodes exclusive to path A should NOT appear in context B
        exclusive_to_a = path_a_ids - {
            msg["node_id"] for msg in engine.get_path_to_node(leaf_b)
        }
        assert context_b_ids.isdisjoint(exclusive_to_a)

    @given(data=tree_with_target())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_context_preserves_order(self, data):
        messages, target_id = data
        engine = BranchEngine(messages)

        context = engine.build_context(target_id)

        # Context should be in root-to-leaf order
        for i in range(len(context) - 1):
            # Each next node's parent should be an ancestor (on the path before it)
            ancestor_ids = {context[j]["node_id"] for j in range(i + 1)}
            assert context[i + 1]["parent_id"] in ancestor_ids


# ---------------------------------------------------------------------------
# Property 4: 删除后树一致性 (Deletion Consistency)
# ---------------------------------------------------------------------------

class TestDeletionConsistencyProperty:
    """After deleting node N:
    - N and all its descendants are removed
    - Remaining nodes' parent_ids point to existing nodes (or None)
    - Tree is still connected (all remaining nodes reachable from root)
    """

    @given(data=tree_with_deletable_node())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_deleted_node_and_descendants_removed(self, data):
        messages, node_to_delete, active_node_id = data
        engine = BranchEngine(messages)

        # Collect descendants before deletion
        descendants = set()
        queue = [node_to_delete]
        while queue:
            current = queue.pop(0)
            descendants.add(current)
            queue.extend(engine._children.get(current, []))

        engine.delete_branch(node_to_delete, active_node_id)

        # None of the deleted nodes should exist
        for nid in descendants:
            assert nid not in engine._nodes
            assert nid not in engine._children

    @given(data=tree_with_deletable_node())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_remaining_parent_ids_valid(self, data):
        messages, node_to_delete, active_node_id = data
        engine = BranchEngine(messages)

        engine.delete_branch(node_to_delete, active_node_id)

        for nid, node in engine._nodes.items():
            parent_id = node.get("parent_id")
            if parent_id is not None:
                assert parent_id in engine._nodes, (
                    f"Node {nid} has dangling parent_id {parent_id}"
                )

    @given(data=tree_with_deletable_node())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_tree_still_connected(self, data):
        messages, node_to_delete, active_node_id = data
        engine = BranchEngine(messages)

        engine.delete_branch(node_to_delete, active_node_id)

        # Find root
        root_id = None
        for nid, node in engine._nodes.items():
            if node.get("parent_id") is None:
                root_id = nid
                break
        assert root_id is not None

        # BFS from root
        visited = set()
        queue = [root_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            queue.extend(engine._children.get(current, []))

        assert visited == set(engine._nodes.keys())

    @given(data=tree_with_deletable_node())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_delete_count_matches_removed_nodes(self, data):
        messages, node_to_delete, active_node_id = data
        engine = BranchEngine(messages)

        nodes_before = set(engine._nodes.keys())

        count = engine.delete_branch(node_to_delete, active_node_id)

        nodes_after = set(engine._nodes.keys())
        actually_removed = nodes_before - nodes_after

        assert count == len(actually_removed)

    @given(data=tree_with_deletable_node())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_non_deleted_nodes_unchanged(self, data):
        messages, node_to_delete, active_node_id = data
        engine = BranchEngine(messages)

        # Collect descendants (will be deleted)
        descendants = set()
        queue = [node_to_delete]
        while queue:
            current = queue.pop(0)
            descendants.add(current)
            queue.extend(engine._children.get(current, []))

        # Snapshot surviving nodes
        surviving_before = {
            nid: (node["node_id"], node["parent_id"], node.get("content"))
            for nid, node in engine._nodes.items()
            if nid not in descendants
        }

        engine.delete_branch(node_to_delete, active_node_id)

        # Verify surviving nodes are unchanged
        for nid, (orig_id, orig_parent, orig_content) in surviving_before.items():
            assert engine._nodes[nid]["node_id"] == orig_id
            assert engine._nodes[nid]["parent_id"] == orig_parent
            assert engine._nodes[nid].get("content") == orig_content


# ---------------------------------------------------------------------------
# Property 5: 向后兼容迁移 Round-Trip (Migration Round-Trip)
# ---------------------------------------------------------------------------

class TestMigrationRoundTripProperty:
    """For any linear message list L:
    - migrate_linear(L) produces a tree where get_path_to_node(leaf)
      returns messages with the same content sequence as L
    - The migrated tree has only one path (no branches)
    """

    @given(messages=linear_messages(min_size=1, max_size=20))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_content_sequence_preserved(self, messages):
        engine = BranchEngine([])
        migrated = engine.migrate_linear(messages)

        # Get the leaf (last message)
        leaf_id = migrated[-1]["node_id"]
        path = engine.get_path_to_node(leaf_id)

        # Content sequence should match original
        original_contents = [msg["content"] for msg in messages]
        path_contents = [msg["content"] for msg in path]
        assert path_contents == original_contents

    @given(messages=linear_messages(min_size=1, max_size=20))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_single_path_no_branches(self, messages):
        engine = BranchEngine([])
        engine.migrate_linear(messages)

        # Every node should have at most one child
        for node_id, children in engine._children.items():
            assert len(children) <= 1, (
                f"Node {node_id} has {len(children)} children after migration"
            )

    @given(messages=linear_messages(min_size=1, max_size=20))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_all_nodes_have_valid_ids(self, messages):
        engine = BranchEngine([])
        migrated = engine.migrate_linear(messages)

        for msg in migrated:
            assert "node_id" in msg
            assert msg["node_id"] is not None
            # Should be a valid UUID
            uuid.UUID(msg["node_id"])

    @given(messages=linear_messages(min_size=1, max_size=20))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_first_node_is_root(self, messages):
        engine = BranchEngine([])
        migrated = engine.migrate_linear(messages)

        assert migrated[0]["parent_id"] is None

    @given(messages=linear_messages(min_size=2, max_size=20))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_linear_chain_structure(self, messages):
        engine = BranchEngine([])
        migrated = engine.migrate_linear(messages)

        # Each subsequent message points to the previous one
        for i in range(1, len(migrated)):
            assert migrated[i]["parent_id"] == migrated[i - 1]["node_id"]

    @given(messages=linear_messages(min_size=1, max_size=20))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_role_preserved(self, messages):
        engine = BranchEngine([])
        migrated = engine.migrate_linear(messages)

        for orig, mig in zip(messages, migrated):
            assert orig["role"] == mig["role"]

    @given(messages=linear_messages(min_size=1, max_size=20))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_node_count_matches(self, messages):
        engine = BranchEngine([])
        migrated = engine.migrate_linear(messages)

        assert len(migrated) == len(messages)
        assert len(engine._nodes) == len(messages)


# ---------------------------------------------------------------------------
# Property 6: 分支切换幂等性 (Branch Switch Idempotency)
# ---------------------------------------------------------------------------

class TestBranchSwitchIdempotency:
    """Consecutive calls to get_path_to_node with the same target
    return the same message sequence (idempotent).
    """

    @given(data=tree_with_target())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_consecutive_path_queries_identical(self, data):
        messages, target_id = data
        engine = BranchEngine(messages)

        path1 = engine.get_path_to_node(target_id)
        path2 = engine.get_path_to_node(target_id)

        ids1 = [n["node_id"] for n in path1]
        ids2 = [n["node_id"] for n in path2]
        assert ids1 == ids2

    @given(data=tree_with_target())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_consecutive_context_builds_identical(self, data):
        messages, target_id = data
        engine = BranchEngine(messages)

        ctx1 = engine.build_context(target_id)
        ctx2 = engine.build_context(target_id)

        ids1 = [n["node_id"] for n in ctx1]
        ids2 = [n["node_id"] for n in ctx2]
        assert ids1 == ids2
