import type {PdfFormCreation} from './pdf-form-create'

let groupSequence=0
export function createPdfFormRadioRows(parent:HTMLElement,pageId:string){
 const doc=parent.ownerDocument,container=doc.createElement('div'),scroll=doc.createElement('div'),table=doc.createElement('table'),caption=doc.createElement('caption'),head=doc.createElement('thead'),heading=doc.createElement('tr'),body=doc.createElement('tbody'),actions=doc.createElement('div'),add=doc.createElement('button'),clear=doc.createElement('button')
 container.className='pdf-form-radio-editor';scroll.className='pdf-form-radio-scroll';scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label','单选选项表格，可横向滚动');table.setAttribute('aria-label','单选选项');caption.textContent='单选选项（坐标单位：PDF 点）'
 for(const text of ['选项值','X','Y','宽度','高度','初始选中','操作']){const cell=doc.createElement('th');cell.scope='col';cell.textContent=text;heading.append(cell)}
 head.append(heading);table.append(caption,head,body);scroll.append(table);actions.className='pdf-form-radio-actions';add.type=clear.type='button';add.textContent='添加选项';add.dataset.pdfRadioRowAdd='true';clear.textContent='清除初始选择';clear.dataset.pdfRadioSelectionClear='true';actions.append(add,clear);container.append(scroll,actions);parent.append(container)
 const name=`pdf-form-radio-initial-${++groupSequence}`,rows:{row:HTMLTableRowElement;value:HTMLInputElement;coords:HTMLInputElement[];checked:HTMLInputElement;remove:HTMLButtonElement}[]=[]
 function update(){add.disabled=rows.length>=64;rows.forEach((item,index)=>{
  const prefix=`选项 ${index+1} `;item.value.setAttribute('aria-label',prefix+'值');item.coords.forEach((input,index)=>input.setAttribute('aria-label',prefix+['左下角 X','左下角 Y','宽度','高度'][index]));item.checked.setAttribute('aria-label',prefix+'初始选中');item.remove.setAttribute('aria-label',`移除选项 ${index+1}`);item.remove.disabled=rows.length<=2
 })}
 function append(value:string,index:number,checked=false){
  const row=doc.createElement('tr'),input=doc.createElement('input');input.type='text';input.value=value;input.maxLength=128;input.dataset.radioValue='true'
  const cell=(element:HTMLElement)=>{const cell=doc.createElement('td');cell.append(element);row.append(cell)};cell(input)
  const coords=[10+index*40,50,20,20].map((value,index)=>{const input=doc.createElement('input');input.type='number';input.step='any';input.value=String(value);input.dataset.radioCoordinate=String(index);if(index>=2){input.min='8';input.max='2000'}cell(input);return input})
  const selection=doc.createElement('input');selection.type='radio';selection.name=name;selection.checked=checked;cell(selection)
  const remove=doc.createElement('button');remove.type='button';remove.textContent='移除';remove.dataset.radioRemove='true';cell(remove)
  const item={row,value:input,coords,checked:selection,remove};rows.push(item);body.append(row)
  remove.onclick=()=>{if(rows.length<=2||remove.matches(':disabled'))return;const focused=row.contains(doc.activeElement);rows.splice(rows.indexOf(item),1);row.remove();update();if(focused)add.focus()}
  update();return input
 }
 append('Yes',0,true);append('No',1)
 add.onclick=()=>{if(rows.length>=64||add.matches(':disabled'))return;let index=rows.length+1;while(rows.some(item=>item.value.value===`Option${index}`))index++;append(`Option${index}`,rows.length).focus()}
 clear.onclick=()=>{for(const item of rows)item.checked.checked=false}
 return {values():NonNullable<PdfFormCreation['radioWidgets']>{return rows.map(item=>{
  const [x,y,width,height]=item.coords.map(input=>input.value.trim()===''?NaN:Number(input.value))
  return {pageId,exportValue:item.value.value,rect:[x,y,x+width,y+height],checked:item.checked.checked}
 })}}
}
