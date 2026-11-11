/** Geometry-only transplant from GenOffice image-edit.ts, pinned ref f8c17004fb730df11f0f743164ffd8b4281bb38c.
 * Excludes Electron bitmap decode, replacement, insertion, deletion, layers and rotation. */
import {createHash} from 'node:crypto'
import {FPDF_PAGEOBJ_TEXT,chainPdfium,loadPdfium,saveDoc,withDocument,type Pdfium} from '../src/main/text-edit'
import {SHARED_TEMPLATE_IMAGE_REASON,chainIsExclusive,formDrawTree,liftOutOfForms,transformRect,walkPageText,type FormChain,type FormDrawTree} from '../src/main/form-text'
const FPDF_PAGEOBJ_IMAGE = 3

type Rect = readonly [number, number, number, number]

interface PageObj {
  obj: number
  index: number
  type: number
  bounds: [number, number, number, number]
}

/** An image object, page-owned or drawn inside a Form XObject (bounds in page space) */
interface ImageObj {
  obj: number
  /** Page object index; for template images, their top-level ancestor's */
  index: number
  bounds: [number, number, number, number]
  chain: FormChain
  ordinals: readonly number[]
}

function collectObjects(m: Pdfium, page: number): PageObj[] {
  const out: PageObj[] = []
  const bl = m._malloc(4)
  const bb = m._malloc(4)
  const br = m._malloc(4)
  const bt = m._malloc(4)
  const count = m._FPDFPage_CountObjects(page)
  for (let i = 0; i < count; i++) {
    const obj = m._FPDFPage_GetObject(page, i)
    if (!m._FPDFPageObj_GetBounds(obj, bl, bb, br, bt)) continue
    out.push({
      obj,
      index: i,
      type: m._FPDFPageObj_GetType(obj),
      bounds: [m.HEAPF32[bl >> 2]!, m.HEAPF32[bb >> 2]!, m.HEAPF32[br >> 2]!, m.HEAPF32[bt >> 2]!],
    })
  }
  for (const p of [bl, bb, br, bt]) m._free(p)
  return out
}

function collectImages(m: Pdfium, page: number): ImageObj[] {
  const out: ImageObj[] = []
  const bl = m._malloc(4)
  const bb = m._malloc(4)
  const br = m._malloc(4)
  const bt = m._malloc(4)
  walkPageText(m, page, FPDF_PAGEOBJ_IMAGE, ({ obj, chain, ordinals, topIndex, toPage }) => {
    if (!m._FPDFPageObj_GetBounds(obj, bl, bb, br, bt)) return
    const local: [number, number, number, number] = [
      m.HEAPF32[bl >> 2]!,
      m.HEAPF32[bb >> 2]!,
      m.HEAPF32[br >> 2]!,
      m.HEAPF32[bt >> 2]!,
    ]
    out.push({
      obj,
      index: topIndex,
      bounds: chain.length > 0 ? transformRect(local, toPage) : local,
      chain,
      ordinals,
    })
  })
  for (const p of [bl, bb, br, bt]) m._free(p)
  return out
}

/** Bounds travel renderer→main unchanged, so matching is tight; the tolerance only
    absorbs float32 round-trips. Closest candidate within tolerance wins. */
const MATCH_TOL = 2

function matchImage(objects: ImageObj[], rect: Rect): ImageObj | null {
  let best: ImageObj | null = null
  let bestD = Infinity
  for (const o of objects) {
    const d = Math.max(
      Math.abs(o.bounds[0] - rect[0]),
      Math.abs(o.bounds[1] - rect[1]),
      Math.abs(o.bounds[2] - rect[2]),
      Math.abs(o.bounds[3] - rect[3]),
    )
    if (d <= MATCH_TOL && d < bestD) {
      best = o
      bestD = d
    }
  }
  return best
}

const firstTextIndex = (objects: PageObj[]): number | undefined =>
  objects.find((o) => o.type === FPDF_PAGEOBJ_TEXT)?.index

/** Lazy per-document census of how often each Form XObject is painted */
type FormExclusive = (pageIndex: number, img: ImageObj) => Promise<boolean>

function formExclusivity(bytes: Uint8Array): FormExclusive {
  let tree: Promise<FormDrawTree> | null = null
  return async (pageIndex, img) => {
    if (img.chain.length === 0) return true
    tree ??= formDrawTree(bytes)
    return chainIsExclusive(await tree, pageIndex, img.ordinals)
  }
}

interface EditGuard {
  exclusive: FormExclusive
  pageIndex: number
}

/** Locate the image under `rect`; a template image is lifted to page level first (as
    the text path does) so the page-owned ops below apply unchanged. Without an
    exclusivity check (preview/render on an in-memory copy) the lift is unconditional. */
async function resolveImage(
  m: Pdfium,
  page: number,
  rect: Rect,
  guard?: EditGuard,
): Promise<ImageObj> {
  const target = matchImage(collectImages(m, page), rect)
  if (!target) throw new Error('the image could not be located on the page')
  if (target.chain.length > 0) {
    if (guard && !(await guard.exclusive(guard.pageIndex, target))) {
      throw new Error(SHARED_TEMPLATE_IMAGE_REASON)
    }
    liftOutOfForms(m, page, target.obj, target.chain)
    target.chain = []
  }
  return target
}

/** Pinned axis-aligned map old bounds → final rect; content orientation survives. */
function applyImageGeometry(
  m: Pdfium,
  obj: number,
  bounds: Rect,
  rect: Rect,
): void {
  const [ox1, oy1, ox2, oy2] = bounds
  const [nx1, ny1, nx2, ny2] = rect
  const ow = ox2 - ox1
  const oh = oy2 - oy1
  if (ow > 1e-6 && oh > 1e-6 && (nx1 !== ox1 || ny1 !== oy1 || nx2 !== ox2 || ny2 !== oy2)) {
    const sx = (nx2 - nx1) / ow
    const sy = (ny2 - ny1) / oh
    // Post-multiplied axis-aligned map old bounds → new rect
    m._FPDFPageObj_Transform(obj, sx, 0, 0, sy, nx1 - sx * ox1, ny1 - sy * oy1)
  }
}


export interface ExistingEngineImage {pageIndex:number;rect:[number,number,number,number];aboveText:boolean;fingerprint:string;pixelsSha256:string;exclusive:boolean}
function fingerprint(m:Pdfium,o:ImageObj){
 const image=m as Pdfium&{_FPDFImageObj_GetImageDataDecoded(obj:number,buffer:number,length:number):number;_FPDFImageObj_GetImagePixelSize(obj:number,width:number,height:number):number}
 const length=m._FPDFImageObj_GetImageDataRaw(o.obj,0,0),decodedLength=image._FPDFImageObj_GetImageDataDecoded(o.obj,0,0),p=m._malloc(Math.max(length,decodedLength,24)),digest=createHash('sha256')
 try{
  if(length<=0||decodedLength<=0)throw Error('image data unavailable')
  m._FPDFImageObj_GetImageDataRaw(o.obj,p,length);digest.update(m.HEAPU8.slice(p,p+length))
  if(!m._FPDFPageObj_GetMatrix(o.obj,p))throw Error('image matrix unavailable')
  digest.update(m.HEAPU8.slice(p,p+24))
  if(!image._FPDFImageObj_GetImagePixelSize(o.obj,p,p+4))throw Error('image pixel size unavailable')
  const width=m.HEAP32[p>>2]!,height=m.HEAP32[(p+4)>>2]!
  if(width<=0||height<=0)throw Error('image pixel size invalid')
  // PDFium may add lossless FlateDecode while saving an originally unfiltered
  // stream. Compare decoded content and dimensions, not its storage encoding.
  image._FPDFImageObj_GetImageDataDecoded(o.obj,p,decodedLength)
  const pixelsSha256=createHash('sha256').update(JSON.stringify([width,height])).update(m.HEAPU8.slice(p,p+decodedLength)).digest('hex')
  return {fingerprint:digest.digest('hex'),pixelsSha256}
 }finally{m._free(p)}
}
export async function listExistingEngineImages(bytes:Uint8Array):Promise<ExistingEngineImage[]>{
 const exclusive=formExclusivity(bytes)
 return chainPdfium(async()=>{const m=await loadPdfium();return withDocument(m,bytes,async doc=>{
  const out:ExistingEngineImage[]=[]
  for(let pageIndex=0;pageIndex<m._FPDF_GetPageCount(doc);pageIndex++){
   const page=m._FPDF_LoadPage(doc,pageIndex);if(!page)throw Error('could not load image page')
   try{const textIdx=firstTextIndex(collectObjects(m,page));for(const o of collectImages(m,page)){
    if(o.bounds[2]-o.bounds[0]<3||o.bounds[3]-o.bounds[1]<3)continue
    out.push({pageIndex,rect:o.bounds,aboveText:textIdx!==undefined&&o.index>textIdx,...fingerprint(m,o),exclusive:await exclusive(pageIndex,o)})
   }}finally{m._FPDF_ClosePage(page)}
  }return out
 })})
}
export async function applyExistingImageTransform(bytes:Uint8Array,pageIndex:number,oldRect:Rect,rect:Rect):Promise<Uint8Array>{
 const exclusive=formExclusivity(bytes)
 return chainPdfium(async()=>{const m=await loadPdfium();return withDocument(m,bytes,async doc=>{
  const page=m._FPDF_LoadPage(doc,pageIndex);if(!page)throw Error('could not load image page')
  try{const target=await resolveImage(m,page,oldRect,{exclusive,pageIndex});applyImageGeometry(m,target.obj,target.bounds,rect);if(!m._FPDFPage_GenerateContent(page))throw Error('could not regenerate image page');return saveDoc(m,doc)}finally{m._FPDF_ClosePage(page)}
 })})
}
