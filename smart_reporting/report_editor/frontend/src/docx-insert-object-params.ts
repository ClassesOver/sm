/** Canonical shape IDs: GenOffice f8c17004 packages/ui/src/shape-gallery.tsx. */
import {WORDART_PRESETS} from './vendor/genoffice-docs/packages/ui/src/wordart-presets'
export const DOCX_OBJECT_SHAPES = ["line", "lineArrow", "lineArrowDouble", "lineBent", "lineCurved", "rect", "roundRect", "snip1Rect", "snip2SameRect", "snip2DiagRect", "snipRoundRect", "round1Rect", "round2SameRect", "round2DiagRect", "ellipse", "triangle", "rtTriangle", "parallelogram", "trapezoid", "diamond", "pentagon", "hexagon", "octagon", "plus", "mathPlus", "pie", "chord", "teardrop", "frame", "halfFrame", "corner", "diagStripe", "donut", "noSmoking", "blockArc", "foldedCorner", "bevel", "cube", "can", "lightningBolt", "heart", "sun", "moon", "cloud", "arc", "plaque", "smileyFace", "leftBracket", "rightBracket", "leftBrace", "rightBrace", "rightArrow", "leftArrow", "upArrow", "downArrow", "leftRightArrow", "upDownArrow", "quadArrow", "bentArrow", "uturnArrow", "curvedRightArrow", "stripedRightArrow", "notchedRightArrow", "chevron", "homePlate", "star4", "star5", "star6", "star7", "star8", "star10", "star12", "star16", "star24", "star32", "irregularSeal1", "irregularSeal2", "ribbon", "ribbon2", "wave", "doubleWave", "flowChartProcess", "flowChartAlternateProcess", "flowChartDecision", "flowChartPredefinedProcess", "flowChartInternalStorage", "flowChartDocument", "flowChartMultidocument", "flowChartTerminator", "flowChartPreparation", "flowChartManualInput", "flowChartManualOperation", "flowChartConnector", "flowChartOffpageConnector", "flowChartMagneticDisk", "flowChartMagneticDrum", "flowChartDisplay", "flowChartDelay", "flowChartOr", "flowChartCollate", "flowChartSort", "flowChartExtract", "flowChartMerge", "flowChartSummingJunction", "flowChartPunchedTape", "wedgeRectCallout", "wedgeRoundRectCallout", "wedgeEllipseCallout", "cloudCallout"] as const
export type DocxInsertObject = {type:'textbox'|'shape'|'wordArt'; preset?:string; text?:string; widthEmu?:number; heightEmu?:number}
export function normalizeDocxInsertObject(value:unknown):DocxInsertObject {
 const bad=():never=>{throw new Error('docx_insert_object_invalid')}
 if(!value||typeof value!=='object'||Array.isArray(value))return bad()
 const v=value as Record<string,unknown>
 if(Object.keys(v).some(k=>!['type','preset','text','widthEmu','heightEmu'].includes(k)))return bad()
 if(!['textbox','shape','wordArt'].includes(v.type as string))return bad()
 if(v.type==='textbox' ? v.preset!==undefined : v.type==='shape' ? !DOCX_OBJECT_SHAPES.includes(v.preset as never) : !WORDART_PRESETS.some(p=>p.id===v.preset))return bad()
 if(v.text!==undefined&&(typeof v.text!=='string'||v.text.length>20000||/[\x00-\x08\x0b-\x1f]/.test(v.text)))return bad()
 for(const k of ['widthEmu','heightEmu'])if(v[k]!==undefined&&(!Number.isInteger(v[k])||(v[k] as number)<9525||(v[k] as number)>20116800))return bad()
 if(v.type==='shape' && ['line','lineArrow','lineArrowDouble','lineBent','lineCurved'].includes(v.preset as string) && v.text)return bad()
 return {...v} as DocxInsertObject
}
