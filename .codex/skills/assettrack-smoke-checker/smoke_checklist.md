# AssetTrack Smoke Test Checklist

## Required setup

- Rebuild with Docker:
  `docker compose up -d --build`
- Use an incognito browser window

## Core workflow seam

`entry → prerequisite selection → scan queue → preview → commit`

## Generic smoke sequence

1. Log in
2. Enter the affected workflow
3. Perform the changed operator action
4. Verify queue or workflow state changed correctly
5. Open preview
6. Verify preview content and messaging
7. Commit
8. Verify result/success path
9. Verify queue clears
10. Verify no obvious regression in nearby workflow if shared code changed

## Pass/fail capture format

- `Step X PASS`
- `Step X FAIL: <plain-language reason>`

## Failure rule

If any step fails:
- stop
- describe what happened
- identify the smallest safe next fix/test step