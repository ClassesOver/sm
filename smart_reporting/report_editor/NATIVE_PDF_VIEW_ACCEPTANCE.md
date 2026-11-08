# PDF source reading-mode and zoom acceptance

2026-11-06; fixed GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`.
Closes night reading and bounded zoom behavior; not the entire View family.

## Original sources

- App.tsx blob `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`, lines2161–2171:
  adjacent source zoom steps with0.001 epsilon, clamping and content anchoring.
  Lines7619–7643: Ctrl/Meta wheel accumulates deltaY×0.006 and anchors the cursor.
  Lines8004–8111: navigation includes thumbnails, outline, comments, comparison,
  attachments, search, spread and night mode. Lines11908–11940 include a status
  slider with min10/max800/step5.
- view-config.ts blob `798e06a8a85291c5ce9631c968bd460ae9b3bd6f`, lines4–9:
 18 steps from0.1 to8: .1/.25/.5/.67/.8/.9/1/1.1/1.25/1.5/1.75/2/2.5/3/4/5/6/8.
- styles.css blob `5304735100e82bf726ed5e396acc2104f6de661d`, lines1185–1196:
  `invert(1) hue-rotate(180deg)` only on page bitmaps, dark viewport background
  and page shadow. Draft overlays, form controls and navigation are separate DOM.

## Native changes

The View night control now toggles the source bitmap-only filter and pressed
state, including readonly documents. Its state is local to the current editor;
no file bytes, NativeDraft operations or save identity change. Print canvases are
created outside the night viewport and retain ordinary rendering.

Home and View use the same18-step ladder,0.1–8 clamp and source epsilon, replacing
the old1.2 multiplier and0.25–4 range. Home gains source zoom-out/in actions; a
status slider and buttons match the source limits/step. Ctrl/Meta wheel uses the
source coefficient and accumulates against the latest synchronous scale so fast
events do not lose ticks. Fit uses the same clamp. Zoom read controls stay usable
for readonly files and do not create a dirty document.

`pdf-view-state.ts` is a small native DOM adapter, not a copied layout engine:
its anchor stores a content point under the cursor/viewport top. After native
page redraw, it resolves the original page ID and restores that point while
headings/gaps remain unscaled. This adapts the source row-anchor principle to
native headings and spread DOM; it does not claim byte-identical source layout.

Review corrected an incomplete earlier View inventory: comments/compare/
attachments were missing, not completed. They are now present in original order,
individually disabled with precise missing-implementation reasons. DOM navigation
order now matches the source's eight entries. These disabled additions are not
counted as functionality completed.

## Verification

Five new focused checks pass for non-preset/epsilon stepping, bounds and nonfinite
values, unscaled-heading anchoring, whitespace, spread-cursor anchoring and stale
page handling; two affected View inventory/outline checks pass. No full frontend
or repository suite was repeated.

`frontend/smoke/pdf-view-source-smoke.mjs` uses production static assets and
Chromium154.0.8037.57, with substituted auth/preview routes. Source
inspection is from the actual previously accepted packed engine; document
rendering, text layers, input controls and wheel events are real PDF.js/Chromium.
This follow-up changes no backend/runtime/schema/signing code.

In a readonly3-page fixture it checks original-order controls and disabled
reasons, night filter/background/pressed state, all18 preset entries, Home/View
step behavior,10%/800% bounds, slider configuration/input and a genuine Ctrl-wheel
event. The source-point anchor before the wheel is(190,274); afterward it is
(190.000000,273.913043), within one pixel.
Observed zoom sequence: [0.9, 1, 1.1, 1, 0.1, 8, 1.35, 1.25, 1, 1.15].

While night mode remains enabled, it prepares all3 original print pages and
intercepts the browser print call. Each canvas is unfiltered with an opaque white
corner. In actual emulated print media the print host is block, the new status
footer is hidden and all print canvas filters are none; afterward the host is
cleaned up. This is CSS/render isolation evidence, not a system-printer or PDF
export/desktop dialog certification. Source/download SHA256 are identical:
`5a3d35c31655d7418a5800ecf414ff1f4e5a25d1e2afc2b5c16cb8eb1a8bb6c7`. NativeDraft is unchanged; console/page errors are empty.

The first smoke used a non-unique locator for three pages and correctly failed;
selecting the intended first page fixed that test. Earlier successful runs and
the failed locator log remain separate. No product guard or browser safety check
was suppressed to pass. Final originals/receipt are in
`/tmp/pr190-pdf-view-browser-evidence-accepted`.

Standard/Slides production builds pass(32.38s/33.21s), including strict frontend
types. Actual budget/budget contract, smoke syntax and diff pass. Existing
third-party chunk warnings remain. No new Node22/SQL/service check is claimed:
the backend/packed runtime is unchanged. Evidence archive:
`/workspace/scratch/pr190-pdf-view-evidence.zip`.

## Remaining View and overall gaps

Comments/compare/attachments, full source keyboard behavior and source reading
position persistence are not implemented. Fit remains the native active-page
host adaptation, rather than every source row/layout rule. Night filter changes
screen colors only and is not document color correction. Source View/whole PDF
parity, other Page/Form Design/conversion families and desktop/deployed/full-app
image acceptance remain open. Flags stay off.
