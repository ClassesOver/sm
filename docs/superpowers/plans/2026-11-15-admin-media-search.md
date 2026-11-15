# Admin Media and Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Complete company-admin media analysis and web search and sync PR 245.
**Architecture:** Capability-scoped encrypted configuration, bounded provider adapters, existing Office-authorized Agno tools and admin cards.
**Tech Stack:** FastAPI, SQLAlchemy, CredentialVault, httpx, Agno, TypeScript/Vitest.
**Spec:** docs/superpowers/specs/2026-11-15-admin-media-search.md

## Global Constraints
- Reuse existing Office sessions and company isolation; admin-only configuration.
- Preserve personal preferences/Skills and document preview/acceptance authority.
- Pin GenOffice source f8c17004fb730df11f0f743164ffd8b4281bb38c and retain provenance.
- No repeated complete repository test suite; run relevant checks.

## Review Focus
- Provider change cannot reuse the previous vendor's key; tests cover masked responses and encrypted storage.
- Stale settings and revoked roles reject reads/writes/tool results; tests cover CAS and post-call revocation.
- URL redirects, private DNS and oversized/invalid media fail before disclosure; test pinned networking and bounds.
- Provider errors never expose response bodies/secrets or silently use another service; test failures and normalization.
- In-flight save/test cannot discard edits or paint a different page; UI tests cover freeze, retention, and dirty navigation.

### Task 1: Provider configuration and adapters
Files: office/provider_catalog.py, provider_settings.py, provider_http.py, provider_runtime.py, schema.py; tests/test_office_providers.py.
Interface: OfficeProviders(office, vault), catalog(actor), save(actor, capability, document), test(actor, capability, document, media), search(actor, query, limit), analyze(actor, media_urls, requirements).
- [ ] Write failing persistence/secret/isolation/CAS and transport/protocol tests; run targeted pytest and see failure.
- [ ] Implement capability table and public catalog, encrypted secret retention/clear, bounded pinned transport, upstream-compatible protocols.
- [ ] Run tests to green and commit.

### Task 2: Authorized APIs and native agent tools
Files: office/api.py, app.py, office/provider_tools.py, office/settings.py; tests/test_office_providers.py.
- [ ] Write failing admin API/CSRF/revocation/tool tests.
- [ ] Wire GET /admin/providers, PUT /admin/providers/{capability}, POST /admin/providers/{capability}/test; runtime service on repository; attach only enabled tools and reauthorize each call.
- [ ] Run API/settings/native Skill regression to green and commit.

### Task 3: Admin source-aligned cards
Files: frontend/src/office-provider-settings.ts, office-provider-settings.test.ts, office-admin.ts, office-settings.css; source notice.
- [ ] Write failing card save/test/dirty/error tests.
- [ ] Add per-capability source-aligned cards, provider/model/key/base URL, explicit save and capability test; separate file-search switch.
- [ ] Run focused Vitest, production build and Chromium smoke; commit.

### Task 4: Review and delivery
- [ ] Fresh independent whole-change review; fix material findings with regression tests.
- [ ] Fetch/reconcile concurrent PR head without force push; push HEAD to feat/genoffice-web and verify PR SHA.
