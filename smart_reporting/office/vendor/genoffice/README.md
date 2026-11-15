# GenOffice skill source snapshot

Upstream: https://github.com/genspark-ai/genoffice

Fixed commit: `f8c17004fb730df11f0f743164ffd8b4281bb38c`.

213 original files (2,575,406 bytes): all 43 `skills/**/SKILL.md` packages,
all 21 recommended-skill translations, the six editors' full renderer AI source
directories, common agent-core source, PPTX operation prompts, and skill import/CLI
integration definitions. Original paths and bytes are preserved. LICENSE and NOTICE
are included. SOURCE-MANIFEST.json records each original Git blob SHA1, SHA256 and
byte size, verified against the fixed upstream tree during download.

These TypeScript files are reference source, not a second desktop AgentLoop or
an executable browser bundle. Copying a skill does not install its CLI, desktop
IPC, search/image provider or document-generation backend. Native Agno adapters
must use the current task's actual tools and preserve its authorization, frozen
scope, preview and explicit acceptance lifecycle. Runtime integration is tracked
separately from this immutable import. README.md and SOURCE-MANIFEST.json are local
provenance files; original source files are never rewritten here.
