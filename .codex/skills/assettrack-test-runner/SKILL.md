---
name: assettrack-test-runner
description: Run AssetTrack tests in a disciplined way, starting with targeted pytest and expanding only when needed.
---

# AssetTrack Test Runner

Use this skill when the task involves validating AssetTrack changes with tests.

## Purpose

Run tests with the smallest safe scope first, then widen only if needed.

## Rules

- Prefer targeted pytest for changed files first.
- If template or shared workflow code changed, run related regression tests next.
- Run broader scope only after targeted and related tests.
- Run the full suite only when requested, when the task exit criteria requires it, or when narrower coverage is insufficient.
- Do not claim tests passed unless they actually passed.
- Report exactly what was run.
- If dependencies or environment are missing, say so plainly.
- Do not add or remove tests unless the task requires it.
- For workflow-affecting changes, remind the operator that Docker rebuild + incognito smoke test is still required.
- Prefer the minimum execution needed to prove the change.

## Standard order

1. Run targeted tests for changed files.
2. Run nearby regression tests if shared workflow code was touched.
3. Run broader related scope if needed.
4. Run the full `pytest -q` suite only when required by the task or when narrower runs do not establish confidence.
5. Summarize failures briefly and plainly.

## Output format

Return:

1. Tests run
2. Result
3. Failures, if any
4. Smallest safe next test step

## Command helper

Use the bundled script when appropriate:

`bash .codex/skills/assettrack-test-runner/run_tests.sh <pytest args>`

Examples:

- `bash .codex/skills/assettrack-test-runner/run_tests.sh tests/test_return_batch.py -q`
- `bash .codex/skills/assettrack-test-runner/run_tests.sh tests/test_issue_location_wiring.py -q`
- `bash .codex/skills/assettrack-test-runner/run_tests.sh tests/test_issue_location_wiring.py tests/test_return_batch.py -q`
- `bash .codex/skills/assettrack-test-runner/run_tests.sh -q`
