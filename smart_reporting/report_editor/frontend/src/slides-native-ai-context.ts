import type {NativeOperation} from './native-draft'
import type {NativeChartKind} from './slides-native-chart-edit'
export interface SlidesAIObject {
 slideIndex:number;elementId:string;name:string;text:string;type?:string
 tableCells?:(string|null)[][];chartKind?:NativeChartKind|null;chartCategories?:string[]|null;chartSeries?:{name:string;values:number[]}[]|null
}
interface Element {id:string;name:string;text:string;type:string;editable:boolean;geometry?:unknown;tableCells?:(string|null)[][];chartEditSafe?:boolean;chartKind?:NativeChartKind|null;chartCategories?:string[]|null;chartSeries?:{name:string;values:number[]}[]|null}
/** 仅从实际能力清单与当前草稿投影生成授权对象，先过滤选区再读取其内容。 */
export function slidesAIObjects(slides:{slideIndex:number;elements:Element[]}[],operations:NativeOperation[],scope:'object'|'slide'|'deck',selectedSlide:number,selectedIds:ReadonlySet<string>):SlidesAIObject[]{
 const changes=operations.filter(op=>op.kind==='editSlides')
 const result:SlidesAIObject[]=[]
 for(const slide of slides)for(const source of slide.elements){
  if(scope!=='deck'&&(slide.slideIndex!==selectedSlide||scope==='object'&&!selectedIds.has(source.id)))continue
  const match=(item:{slideIndex:number;elementId:string})=>item.slideIndex===slide.slideIndex&&item.elementId===source.id
  if(changes.some(op=>(op.deletions as {slideIndex:number;elementId:string}[]|undefined)?.some(match)))continue
  const table=source.type==='table'&&source.tableCells?.some(row=>row.some(cell=>typeof cell==='string'))
  const chart=source.type==='chart'&&source.chartEditSafe===true&&source.chartKind&&source.chartCategories&&source.chartSeries
  if(!table&&!chart&&!(source.editable&&source.geometry))continue
  if((table||chart)&&changes.some(op=>op.slideSize || (op.resetLayouts as number[]|undefined)?.includes(slide.slideIndex) || (op.slideLayouts as {slideIndex:number}[]|undefined)?.some(item=>item.slideIndex===slide.slideIndex) || (op.groupEdits as {slideIndex:number}[]|undefined)?.some(item=>item.slideIndex===slide.slideIndex)))throw new Error('对象结构或版式已变化，请先保存再生成 AI 候选')
  if(table&&changes.some(op=>(op.tableStructures as {slideIndex:number}[]|undefined)?.some(item=>item.slideIndex===slide.slideIndex)))throw new Error('表格结构已变化，请先保存再生成 AI 候选')
  const object:SlidesAIObject={slideIndex:slide.slideIndex,elementId:source.id,name:source.name,type:source.type,text:source.text}
  if(table)object.tableCells=structuredClone(source.tableCells)
  if(chart){object.chartKind=source.chartKind;object.chartCategories=structuredClone(source.chartCategories);object.chartSeries=structuredClone(source.chartSeries)}
  for(const op of changes){
   for(const edit of (op.edits as ({slideIndex:number;elementId:string;text?:string}[]|undefined))??[])if(match(edit)&&edit.text!==undefined)object.text=edit.text
   for(const edit of (op.tableCells as ({slideIndex:number;elementId:string;row:number;col:number;text:string}[]|undefined))??[])if(match(edit)&&typeof object.tableCells?.[edit.row]?.[edit.col]==='string')object.tableCells[edit.row][edit.col]=edit.text
   for(const edit of (op.chartEdits as ({slideIndex:number;elementId:string;kind?:NativeChartKind;categories?:string[];series?:{name:string;values:number[]}[]}[]|undefined))??[])if(match(edit)){
    if(edit.kind)object.chartKind=edit.kind;if(edit.categories)object.chartCategories=structuredClone(edit.categories);if(edit.series)object.chartSeries=structuredClone(edit.series)
   }
  }
  if(table)object.text=object.tableCells!.map(row=>row.map(cell=>cell??'（合并单元格）').join(' | ')).join('\n')
  if(chart)object.text='图表类别：'+object.chartCategories!.join('、')+'；序列：'+object.chartSeries!.map(item=>item.name+' '+item.values.join('、')).join('；')
  result.push(object)
 }
 return result
}
