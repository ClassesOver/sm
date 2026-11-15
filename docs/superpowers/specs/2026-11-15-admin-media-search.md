# Admin media analysis and web search

User approved completing the remaining GenOffice media/search configuration and synchronizing PR 245. Reuse pinned GenOffice settings fields and provider wire protocols. Admin manages image analysis, video analysis and web search independently; personal settings remain unchanged. Configuration includes enabled flag, provider, model (analysis), API key and HTTPS base URL. Existing local file search remains separate.

Use existing Office identity, company boundary and CredentialVault. Keys are encrypted at rest and never returned; blank replacement clears, omitted replacement preserves only for the same provider. Each capability has optimistic concurrency. Provide actual connection/capability tests without saving the draft. Missing deployment encryption keys yield an actionable failure, never plaintext fallback.

Native Agno document agents gain read-only web_search and analyze_media tools when configured. Authorization and enablement are rechecked for every invocation and after outbound work. Media accepts supplied data URLs and public HTTPS references only; no server filesystem access. Reuse existing pinned-IP outbound transport to prevent SSRF and redirects, cap media/response sizes and request time. Provider failures do not silently fall back to another paid service. Search results retain titles, URLs and snippets and are marked as external untrusted evidence, not document citations.

Support upstream BYOK analysis providers using OpenAI-compatible/Gemini protocols and upstream keyed search APIs; omit Genspark desktop authentication and anonymous fallback. Browser cards mirror source capability/provider/model/key/base URL arrangement, clear dirty/save/test states, retain drafts on failures, and support narrow screens.
