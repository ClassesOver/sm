import type {ChartReadSpec} from '@sheets-web/xlsx-engine'
export type WorkbookChartElement = {kind:'chart'|'title'|'legend'|'value-axis'|'category-axis'}|{kind:'series';seriesIndex:number}|{kind:'point';seriesIndex:number;pointIndex:number}
export type ChartElementRegion={element:WorkbookChartElement;contains(x:number,y:number):boolean}
const regions=new Map<string,{chart:ChartReadSpec;regions:readonly ChartElementRegion[]}>()
const key=(unit:string,sheet:string,path:string)=>`${unit}::${sheet}::${path}`
export function setChartElementRegions(unit:string,sheet:string,chart:ChartReadSpec,items:readonly ChartElementRegion[]){regions.set(key(unit,sheet,chart.chartPath),{chart,regions:items})}
export function clearChartElementRegions(unit:string,sheet:string){for(const name of regions.keys())if(name.startsWith(`${unit}::${sheet}::`))regions.delete(name)}
export function hitChartElement(unit:string,sheet:string,chart:ChartReadSpec,x:number,y:number):WorkbookChartElement{const found=regions.get(key(unit,sheet,chart.chartPath));return found?.chart===chart?[...found.regions].reverse().find(item=>item.contains(x,y))?.element??{kind:'chart'}:{kind:'chart'}}
export function narrowChartElement(current:WorkbookChartElement|undefined,next:WorkbookChartElement):WorkbookChartElement{return next.kind==='point'&&!(current&&(current.kind==='series'||current.kind==='point')&&current.seriesIndex===next.seriesIndex)?{kind:'series',seriesIndex:next.seriesIndex}:next}
