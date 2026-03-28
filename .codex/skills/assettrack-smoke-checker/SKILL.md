---
name: assettrack-smoke-checker
description: Enforce AssetTrack manual smoke-test discipline for workflow, queue, preview, and commit behavior.
---

# AssetTrack Smoke Checker

Use this skill when a change affects navigation, redirects, forms, queues, preview pages, commit behavior, workflow state, or operator flow.

## Purpose

Make sure workflow changes are manually validated through the real operator path.

## Rules

- Always require Docker rebuild before smoke testing:
  `docker compose up -d --build`
- Always use an incognito browser session.
- Walk the operator through the real workflow seam:
  `entry → prerequisite selection → scan queue → preview → commit`
- Do not mark a workflow issue done without a manual smoke test.
- Default to exactly two smoke-test steps at a time.
- Report exactly which smoke steps passed or failed.
- Every smoke response must include explicit `PASS` or `FAIL` capture for each step.
- If a step fails, stop and report the smallest safe next step.
- Keep instructions short and linear.

## Minimum smoke test

1. Log in
2. Enter the target workflow
3. Perform the operator action
4. Verify queue/state change
5. Verify preview
6. Verify commit
7. Verify queue clears

## Output format

Return:

1. Smoke test scope
2. Step-by-step checklist
3. Pass/fail capture format using explicit `PASS` / `FAIL`
4. Smallest safe next step if anything fails

## Usage examples

- "Use the assettrack-smoke-checker skill for this issue workflow change."
- "Use the assettrack-smoke-checker skill to produce a two-step smoke test for the return workflow."
