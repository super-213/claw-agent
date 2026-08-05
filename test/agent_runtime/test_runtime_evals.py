import asyncio
import json
from pathlib import Path

from agent_runtime import ToolApprovalRequired, ToolCall
from agent_runtime.builtin_tools import build_tool_registry
from services.executor import CommandExecutor


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_safety_evaluation_set(tmp_path):
    cases = json.loads((ROOT / "evals" / "runtime_safety_cases.json").read_text(encoding="utf-8"))
    files = tmp_path / "files"
    registry = build_tool_registry(
        project_root=tmp_path,
        generated_files_dir=files,
        executor=CommandExecutor(
            cwd=files, generated_files_dir=files, sandbox_backend="restricted-process"
        ),
        allowed_http_domains=("trusted.example",),
    )

    for case in cases:
        call = ToolCall(case["id"], case["tool"], case["arguments"])
        try:
            result = asyncio.run(registry.invoke(call, approved=case["approved"]))
        except ToolApprovalRequired:
            observed = "approval_required"
        else:
            observed = result.error or "success"
        assert case["expected_error"] in observed, case["id"]
