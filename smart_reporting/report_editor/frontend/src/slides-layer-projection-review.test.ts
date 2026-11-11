import { afterEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createSlidesEditorView } from './slides-main'
import { NativeDraft } from './native-draft'

const canvas = vi.hoisted(() => ({ state: undefined as any }))
vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update(state: any) { canvas.state = state }, destroy() {} }) }))
let view: ReturnType<typeof createSlidesEditorView> | undefined
afterEach(() => { view?.dispose(); document.body.replaceChildren(); canvas.state = undefined })

it('来源图表的只读覆盖对象随宿主图表整体投影层级', async () => {
  const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [{ slideIndex: 0, elements: [
    { id: 'background-shape', type: 'shape', name: '来源背景对象', text: '', editable: true, orderEditable: true },
    { id: 'chart', type: 'chart', name: '图表', text: '', editable: false, deletable: true, orderEditable: false, geometry: { x: 0, y: 0, width: 80, height: 40 } },
    { id: 'shape', type: 'shape', name: '形状', text: '形状', editable: true, deletable: true, orderEditable: true, geometry: { x: 0, y: 0, width: 80, height: 40 } },
  ] }] }
  const draft = new NativeDraft({ documentId: 'layer-overlay-review', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} })
  draft.setOperations([{ kind: 'editSlides', order: [0], elementOrders: [{ slideIndex: 0, elementIds: ['shape', 'chart', 'background-shape'] }] }])
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  // 固定源 buildSlideTree 将 chartUserShapes 紧跟在宿主图表之后，并标记为 decoration。
  const nodes = [{ id: 'master-decoration', sourceId: 'master', type: 'shape', decoration: true }, { id: 'background-shape', sourceId: 'background-shape', type: 'shape', background: true }, { id: 'chart', sourceId: 'chart', type: 'chart' }, { id: 'chart-overlay', sourceId: 'user-shape', type: 'shape', decoration: true }, { id: 'shape', sourceId: 'shape', type: 'shape' }].map(node => ({ ...node, box: { x: 0, y: 0, w: 80, h: 40 } }))
  const request = vi.fn(async (path: string) => path === 'deck' ? source : { slides: [{ slideIndex: 0, widthPx: 960, heightPx: 540, nodes }] })
  view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as any, save: shell.save, download: shell.exportPptx })
  await view.ready
  await vi.waitFor(() => expect(canvas.state).toBeDefined())
  expect(canvas.state.slide.nodes.map((node: any) => node.id)).toEqual(['master-decoration', 'shape', 'chart', 'chart-overlay', 'background-shape'])
})
