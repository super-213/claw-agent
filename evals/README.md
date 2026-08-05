# Agent Runtime evaluations

`runtime_safety_cases.json` is a deterministic, provider-independent regression set for
tool argument validation, approval enforcement, path isolation and network domain policy.
The cases are executed by `test/agent_runtime/test_runtime_evals.py`.

Provider normalization, retry recovery, loop detection, interrupted-run recovery,
approval binding, memory authorization and artifact externalization are covered by
`test_runtime_v2.py`. Live multi-model tool-choice evaluation is intentionally kept out
of unit tests because it requires credentials; adapters normalize every provider into the
same `AgentModelResponse` contract before the shared cases are evaluated.
