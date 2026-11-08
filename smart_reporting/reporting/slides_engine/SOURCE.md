# GenOffice slide engine

Vendored from `https://github.com/genspark-ai/genoffice` at commit
`f8c17004fb730df11f0f743164ffd8b4281bb38c`.

The integrated server packages are `agent-core`, `docx-engine`, `pipelines`,
`pptx-engine`, `pptx-ops`, `pptx-render`, and `zip-gate`, mapped directly from
upstream `packages/`. `docx-engine` remains a dependency of the existing engine;
native Word/PDF entry points are separate local integrations described in UPGRADE.md.

The source packages retain their Apache-2.0 license declarations. The upstream
`LICENSE` and `NOTICE` are included in this directory. The existing complete
`packages/pptx-engine/src/vendor/mtx/LICENSE` notice is preserved locally.

Local integration files are the root npm workspace/build configuration and lock,
`bridge/` request adapters, and `packages/pptx-render/src/browser.ts`, which only
exposes browser-safe exports. Bridges preserve artifact output before returning
layout-audit warnings; an audit exception is reported as an issue after writing
the file. These files are not replaced by upstream package updates.

The browser renderer adapter in
`../../report_editor/frontend/src/vendor/genoffice` is tracked separately with
its own source attribution, LICENSE and NOTICE.

Upgrade scope, local patches, verification commands and known typecheck limits
are recorded in `UPGRADE.md`.

Native DOCX bridge adapters reuse the upstream `pPrWithNumPr` and `pPrWithIndLeft`
helpers. The only local `docx-engine` source adaptation against the pinned
package is adding exports to these two existing `generate.ts` functions;
their implementations are unchanged. The `4b55db9` and `f8c17004` upstream
DOCX package trees are identical (`adc5c829f4cf3b5f7426541d784f0a7c61a6ae57`).
The bridge reports the common integration baseline `f8c17004` in `modelSource`.
