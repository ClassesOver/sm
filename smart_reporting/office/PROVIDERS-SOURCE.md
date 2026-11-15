# GenOffice media/search adaptation

Source: https://github.com/genspark-ai/genoffice/tree/f8c17004fb730df11f0f743164ffd8b4281bb38c

Copyright 2026 Mainfunc, Inc. Apache-2.0; see vendor/genoffice/LICENSE.

| Upstream file | SHA-256 |
| --- | --- |
| `packages/ai-provider/src/media.ts` | `12f005067c82525e0fc2c27aa1310b8277dafb9af55b8be4b2138176df5420a1` |
| `packages/ai-provider/src/media-protocols.ts` | `9d160fa8ed6fcb730bb0fc4eb79a8b3fb1667a45d2c3de6e29f94efa11c1de01` |
| `packages/ai-search/src/index.ts` | `b6f7f1b86ea51a9781f24c6d9b7bfd8193d914b505c9ecf1c2692390f5453a39` |
| `apps/shell/src/renderer/src/SettingsModal.tsx` | `1ac3a85186de5656b91433c35ee88e924cbe40eb29b6c277be025ca18b31a49a` |

Adapted provider catalogs, OpenAI/Gemini analysis payloads, eight search request/response mappings and capability/provider/model/key/base URL form arrangement. Office replaces Electron IPC and Genspark authentication with existing company sessions and admin-only encrypted settings. All provider calls use bounded pinned-IP HTTPS; no automatic vendor fallback. Media: at most four image/video inputs, 20 MiB total, public HTTPS or inline data, no local files or Gemini Files API. Search requires an explicit key, including Parallel/Keenable; anonymous desktop fallback is omitted. Model IDs remain editable.

Deployment: API keys use existing `AGENT_MANAGEMENT_CREDENTIAL_KEYS` (Fernet key ring `key-id:base64-key`); preserve old key IDs during rotation. Admin GET returns only `hasKey`. Each capability has its own version; tests are ephemeral and do not save drafts. Company configuration is read for each tool call and rechecked after it completes.

Verification (2026-11-15): 28 provider regressions pass, including every search wire mapping, actual image/video payload construction, encrypted persistence, tenant/admin/CSRF boundaries, key clearing and endpoint changes, runtime policy revocation, private DNS/redirect/size rejection, malformed responses and source-protocol regressions. Related settings/API/native Skill suite passed (43 tests before the additional 12 review regressions). Four admin frontend tests cover draft retention, in-flight freezing, tests that do not save and guarded navigation. Production TypeScript/Vite build and Chromium desktop/mobile UI/API/database flows passed. Provider responses were mocked for deterministic verification; paid-provider live connectivity requires the deployment's credentials and can be checked using each admin card's test button.
