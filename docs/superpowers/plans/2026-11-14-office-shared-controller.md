# Office shared controller integration

## Design and boundaries

Reuse OfficeAIEntry, office-task-dock, office-assistant-panel, progress and NativeDraft without visual changes. One view-free TypeScript controller owns task polling, request/task cancellation, late-start cleanup and acceptance-response fencing. Format adapters capture their existing trusted context and map typed transport calls. UI generations continue to fence asynchronous context capture and rendering, not execute a second polling loop.

A new backend Office task table/state machine is rejected: task_execution remains the intended production truth. Merely sharing dock presentation is insufficient. This patch is the common frontend control seam, reviewed with the Office strategy coordinator, not a completed Codex integration.

Legacy Word/PDF/Office read and Word/PDF/XLSX/PPTX candidate APIs are transitional transport adapters. No runner/model selection or new permission is accepted from the browser. The Word trusted coordinator and Codex launch gate are separate backend changes. A completed read task does not mutate the draft. A successful edit task is a candidate, explicit accept puts it into NativeDraft, and saving remains an independent existing action.

## Implementation

- [x] Add controller contract tests before implementation: shared polling, repeated-start exclusion, request/late-task cancellation, acceptance exclusion and stale fencing, failed-start cleanup.
- [x] Implement OfficeAssistantController without view or format-engine ownership.
- [x] Migrate Word/XLSX/PPTX/PDF read and edit lifecycle adapters, retaining snapshot checks, explicit accept, draft preservation and close/cancel behavior.
- [x] Run focused regressions and controller type check.
- [x] Attempt the frontend suite once; interrupted for full /tmp volume, not a passing suite.
- [ ] Independent review and live browser acceptance in the combined integration stage.

## Verification limits

This patch does not launch Codex, provision a sandbox, register a production route, deploy, or claim real-provider validation. Existing task IDs are opaque; server-side scope/lease/attempt enforcement remains on the backend. Full frontend TypeScript checking exceeded the environment heap at the default limit, and was killed at a 6 GiB heap limit; the isolated controller type check passed. No full-build success is claimed. The single full frontend suite attempt was stopped with exit 130 when /tmp was full; its partial output included 52 slides-native tests failing with ResizeObserver not defined and two slides-native-ribbon availability assertion failures, so it is not represented as a green suite.
