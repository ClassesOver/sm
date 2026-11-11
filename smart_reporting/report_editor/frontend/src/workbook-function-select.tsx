/** 源 Dropdown 的本地原生 select 适配，分类值与顺序不变。 */
export function FunctionCategorySelect<T extends string>({value,options,onPick}:{value:T;options:readonly {value:T;label:string}[];onPick:(value:T)=>void}){
 return <select aria-label="函数类别" value={value} onChange={event=>onPick(event.target.value as T)}>{options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select>
}
