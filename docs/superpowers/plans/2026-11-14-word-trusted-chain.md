# Word trusted chain Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
**Goal:** Connect existing Word start/status/cancel/accept to trusted task receipt through four actual MCP tools, with real provider still disabled.
**Architecture:** Optional dispatcher on NativeAIService reuses its existing single background _run_job and status/event/accept projection. Dispatcher orchestrates existing TaskSession/lifecycle and one injected transport run, no separate runner/model loop. Source of final candidate is repository completed receipt, never model final alone.
**Spec:** ../specs/2026-11-14-word-trusted-chain-design.md
## Constraints
No real Codex startup, new provider loop, deployment or PR. Backend selected without transport fails503; default None preserves old path. Token exp bounded60/session/deadline; current DB authority every call; no bearer/raw reasoning in events. No schema/shared lifecycle edits.
## Tasks
- [ ] RED→GREEN Word-specific ticket codec and real MCP bridge: native_word_task_mcp.py + tests. Explicit purpose and credential validation; async per-call authorizer; NativeWordAITools full-read/single registration/final equality; cancellation and expiry.
- [ ] RED→GREEN Word dispatcher: native_word_task_dispatcher.py + disposablePG/actualDOCX tests. prepare trusted builder+atomic task; existingTaskSession/open/resume/recover→transport.run→registered candidate→CAS→finish. Read completed receipt only for final publication. New epoch invalidates ticket, no longrun implicit renewal.
- [ ] RED→GREEN optional native_ai.py/native_ai_api.py seam: server-only token_hash(cookie), stable task id/clientRequestId, existing tombstones/no fallback; _run_job calls dispatcher instead of provider planner; accept rechecks current receipt/session/base; existing events and explicit save untouched.
- [ ] Real fixture app start/status/SSE/cancel/accept/save with actual syntheticDOCX and independent readback. Target prior Word/builder/persistence regressions only; no repeated full suite.
- [ ] Astra review exact source; cloud pinned deps+disposablePG; record actual failures/warnings and precise testedtree before joint integration.
