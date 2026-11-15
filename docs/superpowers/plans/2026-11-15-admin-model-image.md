# Admin Model and Image Generation Plan

> **For agentic workers:** Use superpowers:executing-plans; user already authorized implementing GenOffice settings and synchronizing PR 245.

**Goal:** Replace model-ID-only administration with encrypted provider configuration and actual model/image execution.
**Architecture:** Extend existing capability storage/cards with chatModel and imageGeneration. Use native Agno OpenAIChat for compatible chat providers, with pinned HTTPS and current-policy checks. Image generation ports pinned GenOffice OpenAI/Gemini/DashScope protocols into the native PPTX draft lifecycle. No replacement agent framework or direct document mutations.
**Tech Stack:** Existing Agno, httpx, SQLAlchemy, FastAPI, TypeScript/Vitest.
**Spec:** Original user requirements in docs/pr245-personal-admin-settings.md and provider semantics in smart_reporting/office/PROVIDERS-SOURCE.md.

## Constraints and Review Focus
- Preserve deployment defaults until capability is explicitly configured; an explicit disabled saved configuration must not silently call deployment credentials.
- Separate company capability versions; encrypted write-only keys and endpoint-switch key reset.
- Agno SDK HTTPS traffic, including streaming, must stay on validated public endpoints; close per-task clients and bound response sizes.
- Generation must validate actual returned image bytes, never leak keys to returned-image URLs, and retain candidate identity/preview/acceptance checks.
- Concurrent role/config revocation must stop new provider calls and prevent returning stale results.

## Tasks
- [x] Add failing catalog/settings/runtime tests for chatModel and imageGeneration, including disabled-vs-unconfigured semantics and source payloads.
- [x] Implement native Agno model selection and controlled SDK transport; generation adapters for supported source providers.
- [x] Integrate Office model selection and native PPTX image preview and acceptance; test model/client isolation and candidate lifecycle.
- [x] Extend source-aligned admin cards and ephemeral tests; preserve deployment fallback inputs where relevant. Run focused UI/backend tests and production build.
- [x] Fresh review, fix material findings, Chromium verification; reconcile and push PR 245.
