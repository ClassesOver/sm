# PPTX batch replacement capacity

Base: `origin/code` b29f8d8. Independent worktree: `dot/pptx-parity`.

## Intent and constraint

Keep the existing GenOffice-derived find/replace dialog and SM visual language.
Prevent a successful-looking Replace All from producing an unsaveable native draft.
The current planner can emit 501 edits, but the shared preview/save validator in
`slides_render.py` rejects more than 500. Existing arrangement planning already
checks that same capacity atomically.

## Approaches

1. Reject an over-capacity replacement before the controller receives the plan
   (recommended). Reuses existing dialog error handling and preserves one-Undo
   semantics. The user can save current edits or narrow the replacement scope.
2. Automatically split the replacement into multiple saves. Rejected: introduces
   implicit persistence, multiple revisions and history changes outside this task.
3. Raise the server limit. Rejected: changes server resource policy without evidence.

## Design

After planning replacement changes on the existing cloned array, reject when the
result exceeds 500 edits. Keep existing content and pending geometry intact. Reuse
the current dialog catch to show a concrete Chinese capacity warning; do not call
`onReplace` and do not clear query/replacement inputs. At exactly 500, replacement
of an already edited object is legal because it does not consume a new slot.
No backend, shared host, CSS, renderer, persistence or other-format changes.

## Acceptance

- 501 safe matching objects: planner rejects; source and incoming edits unchanged.
- 500 safe matching objects: succeeds with all replacements.
- 500 pending edits: updating an existing target succeeds; a new target rejects.
- DOM Replace All at overflow: error visible, no controller commit, inputs remain.
- Repeated failure and a narrowed query subsequently succeed without dialog reopen.
- Existing find/replace focused regression suite remains passing.

Only directed Vitest/jsdom validation is claimed. This does not establish real
browser, HTTP saving, PPTX export or full GenOffice parity.
