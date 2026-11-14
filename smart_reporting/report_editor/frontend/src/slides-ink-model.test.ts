import {expect,it} from 'vitest'
import {inkSlide,eraseInk} from './slides-ink-model'
import type {RenderSlide} from '@genoffice/pptx-render'
const descr=JSON.stringify({v:1,tool:'pen',color:'C00000',width:2,points:[[2,2],[20,10]]})
const node={id:'source',sourceId:'source',type:'picture',name:'aislides-ink saved',descr,box:{x:10,y:10,w:30,h:20,rotationDeg:0}}
const slide={widthPx:960,heightPx:720,nodes:[node,{...node,id:'plain',sourceId:'plain',name:'普通图片'}]} as RenderSlide
const image={slideIndex:0,bytesBase64:'actual',extension:'png' as const,geometry:{x:20,y:30,width:40,height:20},name:'aislides-ink pending',descr}
it('待保存与已保存墨迹合并供命中，清除只碰当前页合法墨迹',()=>{
 const changes={images:[image,{...image,slideIndex:1}],deletions:[]};const projected=inkSlide(slide,0,changes);expect(projected.nodes).toHaveLength(3)
 const erased=eraseInk(changes,slide,0);expect(erased.images).toEqual([{...image,slideIndex:1}]);expect(erased.deletions).toEqual([{slideIndex:0,elementId:'source'}]);expect(changes.images).toHaveLength(2)
 expect(eraseInk(changes,slide,0,['plain'])).toEqual(changes)
})
it('无效descr不被橡皮认领，已删除笔不重复登记',()=>{
 expect(inkSlide(slide,0,{images:[{...image,descr:'broken'}]}).nodes).toHaveLength(2)
 const changes={deletions:[{slideIndex:0,elementId:'source'}]};expect(eraseInk(changes,slide,0).deletions).toEqual(changes.deletions)
})
