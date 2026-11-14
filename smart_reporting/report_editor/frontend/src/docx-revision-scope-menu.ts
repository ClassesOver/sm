import type {RevisionScope} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/revision-filters'
export function createDocxRevisionScopeMenu(commands:{applyScope(action:'accept'|'reject',scope:RevisionScope):void;scopeReason(scope:RevisionScope):string|null;authors():string[]}){
 const element=document.createElement('section');element.className='ribbon-group docx-ribbon-group';element.setAttribute('aria-label','受支持正文修订范围')
 const items=document.createElement('div');items.className='ribbon-group-items'
 const scope=document.createElement('select');scope.dataset.action='revision-scope';scope.setAttribute('aria-label','正文修订处理范围')
 for(const [value,label] of [['next','当前／下一条'],['all','全部受支持正文'],['shown','当前标记筛选'],['selection','当前选区'],['author','指定作者']]){const option=document.createElement('option');option.value=value;option.textContent=label;scope.append(option)}
 const author=document.createElement('select');author.dataset.action='revision-scope-author';author.setAttribute('aria-label','正文修订作者')
 const selectedScope=():RevisionScope=>scope.value==='author'?{author:author.value}:scope.value as RevisionScope
 const buttons=(['accept','reject'] as const).map(action=>{const button=document.createElement('button');button.type='button';button.className='rb-icon docx-ribbon-command';button.dataset.action='revision-scope-'+action;button.textContent=action==='accept'?'接受此范围':'拒绝此范围';button.onmousedown=event=>event.preventDefault();button.onclick=()=>{if(commands.scopeReason(selectedScope())===null)commands.applyScope(action,selectedScope());refresh()};return button})
 function refresh(){
  const authors=commands.authors(),before=author.value
  if(JSON.stringify(Array.from(author.options,option=>option.value))!==JSON.stringify(authors)){author.replaceChildren(...authors.map(name=>{const option=document.createElement('option');option.value=name;option.textContent=name||'未知作者';return option}));if(authors.includes(before))author.value=before}
  author.hidden=scope.value!=='author';author.disabled=!authors.length
  const reason=scope.value==='author'&&!authors.length?'没有可处理作者':commands.scopeReason(selectedScope())
  for(const button of buttons){button.disabled=reason!==null;button.title=reason??'仅处理服务端授权的简单正文插入／删除；不处理复杂或其它story修订'}
 }
 scope.onchange=refresh;author.onchange=refresh;items.append(scope,author,...buttons)
 const caption=document.createElement('div');caption.className='ribbon-group-label';caption.textContent='受支持正文范围';element.append(items,caption);refresh()
 return {element,refresh}
}
