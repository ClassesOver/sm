# Word range-link acceptance

## Delivered slice

The existing Insert Link/Edit Link/Remove Link controls now operate on an actual selected text range, or the current existing link, in an anchored editable body paragraph, heading or list item. They reuse the pinned GenOffice link mark, run representation and DOCX relationship allocator. No vendor file or dependency was changed.

The operation is `setParagraphLink` with exactly `kind`, `blockId`, `expectedObjectSha256`, `from`, `to`, `href`. Bounds use UTF16 offsets in the current composed paragraph text, never split a surrogate pair, and require the original file/object identity. `href:null` removes a link. New targets are bounded absolute HTTP/HTTPS/mailto URLs without whitespace, control characters or URL credentials. No client-supplied XML, resource path or relationship ID enters this protocol.

Link-only differences are emitted over the smallest changed spans; unrelated marks, link tooltips and paragraph content remain intact. Undo/Redo and local draft replay use the same operation, and unknown fields or incompatible tooltip grouping are rejected rather than discarded during restoration.

## Explicit limits

- New unanchored paragraphs, table cells, cross-paragraph selections and complex inline structures cannot acquire links through these controls. They retain an unavailable explanation.
- A source paragraph that still contains any link cannot change its body text. To change that text, remove all its links, save, then edit the new revision. This avoids implicitly redistributing hyperlink ranges and metadata through a whole-paragraph replacement. Plain-source text replacement followed by adding a link is supported and is covered by the HTTP test.
- Internal bookmarks, unsafe source targets, unmodeled hyperlink attributes such as `w:history`/`w:tgtFrame`, and source relationships whose tooltip differences the pinned parser would merge remain read-only.
- This is range-link support, not complete Word Insert tab parity, a rich linked-paragraph text editor, or desktop Word certification.

## Counterexample and fix

Independent review reproduced a real preservation defect: start with an external link `ABC` containing no run properties, then change only `B` to a new target. The upstream serializer added `Hyperlink` character style to untouched `A/C` while rebuilding the paragraph. The initial test used an explicitly formatted link and did not expose this case.

The bridge now preserves the plain styling of every original link without a character style before regeneration, including untouched fragments and other links in the same paragraph. It retains existing `plain` values and uses the original raw run properties where present. The fixed upstream implementation was not modified.

The reviewer reran the original independent python-docx/OOXML probe: `A` and `C` retained the old href, `B` had the new href, and all three had no added character style. A further targeted test verifies another unstyled link in the same paragraph and paragraph-only formatting. Tooltip-group combinations which cannot be faithfully emitted are explicitly rejected in both backend application and frontend diff/replay.

## Verification evidence

| Layer | Result and scope |
| --- | --- |
| Frontend | 61 focused operations/ribbon/real-Tiptap selection/history cases passed; two later guard regressions (tooltip grouping and unknown restored fields) passed separately. Includes new/cross-block/surrogate/stale/readonly selection rejection |
| Backend | New link module: 27 passed before the independent preservation fix; five added/affected cases passed after that fix. Existing DOCX bridge: 86 passed before that final fix; not redundantly rerun |
| Build | Both final production builds, actual chunk budget and budget contract passed after the last frontend guard change; existing third-party chunk warnings remain |
| Independent review | Original `ABC` counterexample was rerun after the fix and passed |
| HTTP | DOCX roundtrip now composes replace text, spacing, section layout and a range link, independently checking actual external relationship/text. Host run passed; final production-packed bridge run in Node 22, read-only `--network none` container passed (1 passed, 12.72s) |
| Browser/file | Chromium 154 passed native-input preflight, native keyboard text selection, invalid-target rejection, insert/edit/remove, Undo/Redo, actual refresh, three saves/downloads and independent revision reopening through revisions 2/3/4 |

The final browser fixture explicitly includes a same-paragraph untouched external link without run properties and with a tooltip, plus another linked paragraph. Each download independently verifies text, mixed bold/italic, both untouched links/tooltips, and absence of an injected character style on the same-paragraph untouched link. Its API authorization/revision storage are route substitutes; the actual DOCX patcher uses a separate production-packed bridge directory without source/npm modules. Validation deliberately fails while the Word download remains available. The HTTP test separately exercises real ASGI middleware/routes with the existing in-memory repositories; neither establishes production database or deployed network acceptance.

Final browser source SHA-256: `510314f527de3a66020cf854a59d497767288e7c416cd8c094a474099284b703`; final revision-4 SHA-256: `36db5075cec249ba805717b7712964b05aa3184e59d414fb915b7cad65d203b5`. Fixture generation metadata can change hashes between runs; each run verifies its own immutable source and every downloaded revision.

Local evidence: `/tmp/pr190-word-links-evidence/evidence.json` and `revision-1.docx` through `revision-4.docx`; logs: `/tmp/pr190-docx-links-browser-final.log`, `/tmp/pr190-docx-links-http-final.log`. Source is the current working tree above PR head `0017ff7a22cb7931eb8dc387b0eb98b14601d933`; upstream remains `f8c17004fb730df11f0f743164ffd8b4281bb38c`.

## Reproduction

After installing existing npm lockfiles, from the repository root:

```sh
(cd smart_reporting/reporting/slides_engine && npm run bundle:bridges -- --metafile=dist/metafile.json)
node docker/package-office-engine.mjs smart_reporting/reporting/slides_engine /tmp/pr190-word-links-runtime
(cd smart_reporting/report_editor/frontend && \
 REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
 AGENT_REPORTING_SLIDES_ENGINE_DIR=/tmp/pr190-word-links-runtime \
 DOCX_LINK_SMOKE_EVIDENCE_DIR=/tmp/pr190-word-links-evidence \
 node smoke/docx-hyperlink-smoke.mjs)
```

For a host ASGI reproduction with that packed bridge:

```sh
AGENT_REPORTING_SLIDES_ENGINE_DIR=/tmp/pr190-word-links-runtime \
AGENT_WORKSPACE_HMAC_SECRET=test-only-workspace-secret-0123456789 \
AGENT_REPORT_PUBLIC_BASE_URL=https://reports.test.invalid \
.venv/bin/python -m pytest \
 'smart_reporting/reporting/tests/test_native_ribbon_http_roundtrip.py::test_ribbon_operations_use_real_http_save_download_and_reopen[docx]' -q --tb=short
```

For the network-isolated Node 22 variant, reuse the Python/source/engine mounts from `NATIVE_RIBBON_OFFLINE_ACCEPTANCE.md`, mount `/tmp/pr190-word-links-runtime` at `/opt/reporting-slides-engine`, and run only this DOCX node ID. It is a mounted runtime probe, not a completed full application image.

Feature flags remain off. No push, merge or deployment was performed; Word tables/independent headers and footers, full four-format source parity, complete clean-image/browser acceptance and production database/host integration stay open.
