# PDF shared sidebar sizing and thumbnail lifecycle acceptance

2026-11-09; bounded continuation in PR #196, not whole desktop/PDF parity.

## Primary source and behavior

Pinned GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`:
view-config.ts sidebar constants/clamp/load helpers are extracted unchanged;
App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d` sidebarW,
thumbRasterW, startSidebarResize and window clamp are primary references.
`genoffice-pdf-sidebar-source.json` records original/extraction hashes and native
adaptations; full original files are archived.

Thumbnails, outline, comments and attachments share a150px default width and
the source shared preference key. Source limits remain120px minimum/320px maximum,
with maximum capped at40% of window width; effective minimum follows that cap in
very narrow windows. Default values are also clamped. This is a cosmetic shared
browser preference, not document data; storage errors remain nonfatal.

A focusable vertical ARIA separator controls the active pane and exposes current
bounds/value. Pointer dragging is frame-coalesced and persists only on release.
Arrow keys adjust10px, Home/End choose bounds and persist. Escape, pointercancel,
lost capture, window blur, panel switch and disposal cancel without persistence,
restore the starting width and exact prior body cursor/userSelect. Window shrink
clamps the current width without rewriting the stored preference; as in source,
expanding keeps that clamped width until another adjustment/reload.

Thumbnail CSS follows the pane during drag; committed raster width changes only
on release/keyboard actions. Native measured pane chrome replaces desktop24px
assumptions; DPR is capped at2. Per-document/per-original-page cache retains one
geometry/raster variant per page. IntersectionObserver renders near-visible images;
far-offscreen, deleted, replaced and old-document bitmaps release, with canceled
render tasks tracked. Thumbnail work is bounded around4M pixels/16K dimensions.
Original and actual-preview documents never share image objects. This does not
claim new unsaved-annotation thumbnail overlays or full desktop thumbnail parity.

Pagehide can arrive during a fit/raster refresh. The view now saves the last stable
source position plus latest zoom/fit intent rather than discarding that update.
Initial-load and preview-transition readiness guards still prevent a temporary top
position or output-preview state from overwriting the source record. No backend,
write schema, file operation or dependency change.

## Acceptance evidence

- 19 existing targeted reading/fit/zoom checks pass; no new unit cases or full suite
are claimed for this reversible UI change.
- A new production-static Chromium154.0.8037.57 compound scenario uses30 real pages,
form fields, notes, a real outline and DPR2. Initial lazy rendering rasterizes only
5 of30 thumbnails. A150→230px drag keeps the same canvas object and
251px bitmap until release, then produces a410px bitmap. It checks pointer
clamping, Escape/pointercancel/blur/panel-switch cancellation, keyboard bounds,
ARIA controlled panes, hide/reopen, shared widths, mobile156px cap without changing
stored260px preference, immediate resize/reload fit restoration, readonly,
corrupt/denied storage and active-drag teardown restoring body styles.
- The same scenario scrolls to a far thumbnail, verifies offscreen release, deletes
that page and verifies its bitmap releases. Actual preview uses different images;
resizing it and returning to source do not change the draft. Only the explicitly
added note/delete/normalized order remain. Six affected browser scenarios pass:
all-row fit/form focus, View/zoom/print, reading, occurrence search, comments and
attachment read/export.
- Independent pypdf verifies source/download bytes identical and preview30→29 pages
(original0 through28), original content/text/boxes/rotation/UserUnit, form values/
widget AP, original notes and outline destination preserved. The explicit new note
exists; sidebar operations add no PDF changes.
- Final Standard38.04s/Slides35.36s builds, configured Standard budget, source hashes,
smoke syntax and diff pass. Slides has no equivalent configured budget. Backend
unchanged; previous Node22 results are not counted anew. No whole suite repeated.

Source/download SHA256: `18decca1a8c17a6fd62ec8eb6b702eb80b0c3235a0b3f014cc1f0e3384365601`.
Actual preview SHA256: `be024e92b8d3f3cf827e5f05d8a3779493abb9a6246cd9cb1cfc5f116062ed44`.
Evidence: `/workspace/scratch/pr196-pdf-sidebar-evidence.zip`.

The browser initially exposed immediate resize/reload dropping the latest fit
mode while reflow was unfinished. The stable-position/latest-intent fallback fixes
it without relaxing the original initial-restore/preview guards; original failure
and final passing records remain archived. Browser auth/revision routes are
substitutes, not production SQL/auth evidence.

Desktop side-note margin/full host layout, full shortcuts/comparison, reply and
attachment mutation, other PDF families, full application image and deployed
identity/network acceptance remain open. Flags stay off; no merge/deploy.
