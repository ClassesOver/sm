# Workbook engine source

Vendored from local sheets-web/packages/xlsx-engine, package @sheets-web/xlsx-engine 0.1.0, on 2026-11-03. The supplied sheets-web checkout has no committed HEAD; SOURCE-SHA256.json pins the exact source snapshot. Upstream provenance (genoffice f5247d3 and later local extensions) is preserved in UPSTREAM.md. License: Apache-2.0, as declared by sheets-web and its package manifests.

Only this engine and its tests are migrated. Node bridge and report integration are smart_reporting additions. Browser and server import this same package. No runtime dependency on adjacent sheets-web sources.

## 2026-11-05 selective upstream maintenance

Reviewed GenOffice `4b55db9ed1994575a695160ffc6cfd0bfc866211` (2026-11-04 snapshot). The engine remains the sheets-web browser-safe subset, with three upstream fixes backported: Excel 1900 serial-date grouping (`92ab9c46`), numeric text in baked pivot aggregates/calculated fields (`17cd6e4a`), and deterministic non-finite sort keys (`69880bc8`). See UPSTREAM.md for scope and exclusions. This is not a replacement with the complete latest `@genoffice/xlsx-gateway`.

SOURCE-SHA256.json retains the original migrated sheets-web snapshot. LOCAL-ADAPTATIONS-SHA256.json records the already adapted package manifest: its current bytes equal git HEAD and already differed from the source snapshot before this maintenance. UPSTREAM-PATCHES-SHA256.json pins the local files changed or added by this maintenance, including its new regression test. Apply the manifests in that order; later entries take precedence. Together they cover every file under packages/xlsx-engine (77 files), not the local bridge, root toolchain, documentation, LICENSE/NOTICE, or the hash manifests themselves. The exclusions are not upstream source claims. The manifests do not imply that unported upstream features are present.

Latest review: `f8c17004fb730df11f0f743164ffd8b4281bb38c` (2026-11-05). The additional six upstream commits add desktop external-link break/retarget, formula-settle export and printing features; those depend on desktop/Rust gateway modules absent from this browser-safe subset. They are not claimed as integrated. Existing three backports remain unchanged.
