/** Page setup geometry from GenOffice f8c17004 MarginDialog / LayoutTab. */
export interface PageMargins { top: number; right: number; bottom: number; left: number }
export const LAST_CUSTOM_MARGINS_KEY = 'aidocs.marginLastCustom'
export const MARGIN_PRESETS = [
 { key:'1440', name:'普通',top:1440,right:1440,bottom:1440,left:1440 },
 { key:'720', name:'窄',top:720,right:720,bottom:720,left:720 },
 { key:'moderate', name:'适中',top:1440,right:1080,bottom:1440,left:1080 },
 { key:'wide', name:'宽',top:1440,right:2880,bottom:1440,left:2880 },
 { key:'mirrored', name:'镜像',top:1440,right:1440,bottom:1440,left:1800 },
 { key:'office2003', name:'Office 2003 默认',top:1440,right:1800,bottom:1440,left:1800 },
] as const
export const marginsFitPage = (m:PageMargins,w:number,h:number) => [m.top,m.right,m.bottom,m.left].every(v=>Number.isSafeInteger(v)&&v>=0&&v<=31680) && m.left+m.right<=w-1440 && m.top+m.bottom<=h-1440
export function readLastCustomMargins():PageMargins|null {
 try { const m=JSON.parse(localStorage.getItem(LAST_CUSTOM_MARGINS_KEY)??'null'); return m&&Object.keys(m).length===4&&['top','right','bottom','left'].every(k=>Number.isSafeInteger(m[k])&&m[k]>=0&&m[k]<=31680)?m:null } catch { return null }
}
export function rememberCustomMargins(m:PageMargins) { try { localStorage.setItem(LAST_CUSTOM_MARGINS_KEY,JSON.stringify(m)) } catch { /* Storage is optional; the accepted layout edit remains valid. */ } }
export const paperSizeInRange=(w:number,h:number)=>[w,h].every(v=>Number.isSafeInteger(v)&&v>=144&&v<=31680)
