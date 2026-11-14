/** 固定源 DrawTab 的本地显示依赖；控件结构与事件保留在源组件。 */
import React from 'react'
export const BIG=28
export type RibbonPanelKey='pen'
export const closeSiblingPanels=(_event:React.MouseEvent,close:(keep:RibbonPanelKey[])=>void,key:RibbonPanelKey)=>close([key])
export const RbCaret=()=> <span className="rb-caret" aria-hidden>▾</span>
export const Group=({label,children}:{label:string;children:React.ReactNode})=><section className="ribbon-group"><div className="ribbon-group-items">{children}</div><div className="ribbon-group-label">{label}</div></section>
const labels:Record<string,string>={ribbonGroupDrawTools:'绘图工具',ribbonGroupSelect:'选择',ribbonSelectTip:'选择：退出绘图，回到元素编辑',ribbonEraser:'橡皮擦',ribbonEraserTip:'擦除命中的整笔墨迹',ribbonPen:'笔',ribbonHighlighter:'荧光笔',ribbonPencil:'铅笔',ribbonInkThickness:'粗细',ribbonInkColors:'颜色',ribbonMoreColors:'更多颜色…',ribbonInkDelete:'删除',ribbonInkAdd:'添加',ribbonInkAddTip:'添加笔、荧光笔或铅笔',ribbonGroupPens:'笔',ribbonGroupClear:'清除',ribbonEraseAll:'全部清除',ribbonEraseAllTip:'清除当前页的全部墨迹',ribbonInkWidthTip:'{w} 像素'}
export const useI18n=()=>({t:(key:string,vars?:Record<string,unknown>)=>(labels[key]??key).replace(/\{(\w+)\}/g,(_all,name)=>String(vars?.[name]??''))})
