# Workbook engine source

Vendored from local sheets-web/packages/xlsx-engine, package @sheets-web/xlsx-engine 0.1.0, on 2026-11-03. The supplied sheets-web checkout has no committed HEAD; SOURCE-SHA256.json pins the exact source snapshot. Upstream provenance (genoffice f5247d3 and later local extensions) is preserved in UPSTREAM.md. License: Apache-2.0, as declared by sheets-web and its package manifests.

Only this engine and its tests are migrated. Node bridge and report integration are smart_reporting additions. Browser and server import this same package. No runtime dependency on adjacent sheets-web sources.

The local static report image extension in `src/chart-add.ts` reuses the existing drawing, anchor, relationship, and package pipeline. `LOCAL-ADAPTATIONS-SHA256.json` pins the modified engine file. Server-only file identity checks are in `bridge/images.ts`.
