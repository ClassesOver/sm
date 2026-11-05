GenOffice https://github.com/mainfunc/genoffice at
f8c17004fb730df11f0f743164ffd8b4281bb38c, under Apache-2.0.

The following files are copied without modification from `apps/slides/src/`,
with the same relative paths:

- `renderer/NodeBody.tsx`
- `renderer/ChartBody.tsx`
- `renderer/konva-adapter.ts`
- `renderer/canvas-colors.ts`
- `renderer/text-warp.ts`
- `renderer/text-hit-area.ts`
- `shared/cjk-script.ts`

All seven files are byte-identical between the previous baseline
`c9c7a5da42cb6707e829f1968f320db69a7763c5` and this revision. `LICENSE` and
`NOTICE` are the unmodified upstream root files at this revision.

The local browser integration remains in `src/slides-canvas.tsx` and
`src/slides-canvas-model.ts`: it consumes the server RenderTree, loads embedded
image data URLs, and limits selection and geometry edits to server-authorized
editable IDs. Upstream desktop application, filesystem, AI-provider and document
export integrations are not vendored here. The renderer resolves
`@genoffice/pptx-render` to the matching local slides engine through TypeScript
and Vite aliases. No dependency changes are required for this revision.
