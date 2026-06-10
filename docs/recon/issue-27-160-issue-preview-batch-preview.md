# Issue 27-160: Issue Preview And Generic Batch Preview Recon

## 1. Summary

The protected workflow seam is intact in the current code:

`entry page -> prerequisite selection -> scan queue -> preview -> commit`

`/issue` renders the Issue queue page directly after holder selection. `/return` renders the Return queue page directly. Neither route redirects to preview.

The confusing surface is presentation/navigation: Issue Preview still links back to the generic Batch Preview page, and generic `/preview` still contains an Issue Mode branch. That can make generic preview feel like a workflow hub instead of a direct-only Add Assets review surface.

No route, queue, commit, custody, event, audit, schema, persistence, auth, or permission change is needed for this recon.

## 2. Current Route/Template Behavior

| Surface | Current behavior | Notes |
| --- | --- | --- |
| `/issue` | Requires login, enables `issue_mode`, requires an active selected holder, then renders `return_queue.html` with Issue labels. | If no holder is selected, it redirects to `/holders?return_to=/issue`. It does not redirect to preview. |
| Issue queue template | Uses `Review Before Issue` and posts scans with `return_to=/issue`. | This reads as a workflow queue step, not a generic preview entry. |
| `/issue/preview` | Requires `issue_mode`, active selected holder, current location context, and queued asset tags. | If `issue_mode` is off or the queue is empty, it redirects back to `/issue`. |
| `issue_preview.html` | Renders Issue Preview, holder, current location, assets, blocked items, and Issue commit controls. | Its local nav points to generic `/preview` with `Back to Batch Preview`. |
| `/return` | Requires login and renders `return_queue.html` with Return labels. | It does not redirect to preview. |
| `/return/preview` | Requires login and renders `return_preview.html` from the current queue state. | Empty queue renders a neutral empty state; meaningful preview assumes queued assets. |
| `return_preview.html` | Local nav points back to `/return` with `Back to Return Queue`. | This is clearer than Issue Preview's generic back link. |
| `/preview` | Direct generic Batch Preview route built from `SCAN_QUEUE`. | It is not in main navigation, but direct URL still loads. |
| `preview.html` | Renders batch rows, generic commit, and an `Issue Mode` section. | When Issue Mode is enabled, it links to holder search and `/issue/preview`. |
| `/add-assets/review` | Admin-only review handoff for direct Add Assets. | Blocks empty queue before redirecting to `/preview`. |

## 3. Current Wording/Navigation Findings

- `issue_preview.html` shows `Back to Batch Preview`, linking to generic `/preview`.
- `return_preview.html` shows `Back to Return Queue`, linking to `/return`.
- `return_queue.html` uses `Review Before Issue` and `Review Before Return`, which supports the queue -> preview seam.
- `preview.html` still includes `Issue Mode`, `Search/select holder`, and `Review issue details`.
- Main navigation does not show generic Preview. Tests confirm `/preview` stays direct-only while Issue and Return stay visible.

The highest-risk wording is `Back to Batch Preview` on Issue Preview. It implies Issue Preview is subordinate to generic Batch Preview, even though the operator path should be Issue queue -> Issue Preview -> Commit Issue.

The second risk is the Issue Mode section on generic `/preview`. It makes generic preview look like a possible Issue workflow starting point or branching hub, especially if an operator reaches it by direct URL.

## 4. Risk Assessment

| Risk | Level | Reason |
| --- | --- | --- |
| Change `Back to Batch Preview` wording/link in Issue Preview | Low | Presentation-only if it links back to `/issue` and keeps commit behavior unchanged. |
| Clarify generic `/preview` copy for Add Assets/direct batch review | Low-medium | Copy/layout only, but tests may assert existing labels. |
| Remove or demote generic `/preview` Issue Mode controls | Medium | It may affect older direct Add Assets paths and tests that still exercise Issue Mode through `/preview`. |
| Redirect `/issue` or `/return` to preview | High | Would violate the protected workflow seam and make preview an entry route. |
| Make generic `/preview` the starting point for Issue | High | Preview assumes a populated queue and should not replace entry/prerequisite/queue steps. |
| Change queue or commit behavior to solve wording confusion | High | Out of scope and risks custody/event workflow behavior. |

## 5. Invariant Impact

No invariant violation was found in current route behavior.

Required constraints remain true:

- Events remain append-only.
- Audit history remains untouched.
- Custody state still derives from event history.
- Issue and Return entry routes render workflow pages directly.
- Preview is not introduced as an entry route.
- Issue Preview redirects an empty queue back to `/issue`.
- Generic Add Assets review blocks empty queue before opening `/preview`.
- Commit-time checks remain responsible for final safety.

Any implementation follow-up should preserve the workflow seam and avoid changing queue, commit, route, permission, custody, event, audit, schema, or persistence behavior.

## 6. Recommendation

Open a small Class 1 follow-up to clarify Issue Preview local navigation:

- Replace the Issue Preview `Back to Batch Preview` local nav with Issue-specific wording.
- Prefer `Back to Issue` or `Back to Issue Queue`.
- Link back to `/issue`, not generic `/preview`.
- Keep all Issue Preview commit controls, validation, holder display, current location display, blocked-item handling, and queue behavior unchanged.
- Add/update focused tests only for the local nav wording/link and existing direct `/issue` behavior.

Treat the generic `/preview` Issue Mode section as a separate follow-up. It needs a more careful decision because current tests still exercise Issue Mode behavior through `/preview`.

No route behavior change is recommended in this issue.

## 7. Suggested Follow-Up Issue Bodies

### Follow-Up A: Clarify Issue Preview Local Navigation

**Task:** Replace Issue Preview's generic Batch Preview back link with Issue-specific local navigation.

**Change classification:** Class 1 - UI / Presentation

**Scope:**

- Update `issue_preview.html` local nav only.
- Replace `Back to Batch Preview` with `Back to Issue` or `Back to Issue Queue`.
- Link the action to `/issue`.
- Keep Issue Preview commit behavior unchanged.
- Keep holder, current location, blocked items, queue, and validation behavior unchanged.
- Add/update focused tests for Issue Preview local nav and direct Issue entry behavior.

**Non-goals:**

- Do not change routes.
- Do not change redirects.
- Do not change Issue workflow behavior.
- Do not change Return workflow behavior.
- Do not change generic `/preview`.
- Do not change queue or commit behavior.
- Do not change schema, permissions, custody logic, event history, audit history, or persistence.

**Verification:**

- `/issue` renders Issue queue page directly.
- `/issue/preview` with queued assets shows Issue Preview.
- Issue Preview local nav returns to `/issue`.
- Empty Issue Preview still redirects to `/issue`.
- `python3 -m compileall assettrack tests`
- Focused Issue preview tests.

### Follow-Up B: Review Generic Batch Preview Issue Mode Surface

**Task:** Decide whether the generic Batch Preview page should still show Issue Mode controls or whether those controls should be demoted/clarified.

**Change classification:** Planning / Recon first, then likely Class 1 if only wording/layout changes are approved.

**Scope:**

- Review `preview.html`, `/preview/mode`, `/preview/commit`, `/issue/preview`, and direct Add Assets review behavior.
- Identify tests that still depend on Issue Mode through `/preview`.
- Recommend whether to keep, demote, relabel, or remove visible Issue Mode controls on generic `/preview`.
- Preserve direct `/preview` availability for authorized users.
- Preserve `/issue` as the Issue entry route.
- Preserve `/return` as the Return entry route.

**Non-goals:**

- Do not change route behavior without a separate approved implementation issue.
- Do not make preview an entry route.
- Do not change Issue or Return workflow behavior.
- Do not change queue or commit behavior.
- Do not change schema, permissions, custody logic, event history, audit history, or persistence.

**Verification:**

- Confirm `/preview` remains direct-only and absent from normal navigation.
- Confirm `/issue` and `/return` render workflow pages directly.
- Confirm direct Add Assets review still reaches generic preview with a populated queue.
- Confirm preview commit and Issue commit tests still pass if implementation is later approved.
