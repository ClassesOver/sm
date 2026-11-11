import { expect, it } from 'vitest'
import { imagePlacement, prepareSlideImage } from './slides-native-images'

it('图片按固定源96dpi尺寸居中，大图保持比例缩到8.5英寸',()=>{
 expect(imagePlacement({cx:12192000,cy:6858000},{width:100,height:50})).toEqual({x:590,y:335,width:100,height:50})
 expect(imagePlacement({cx:12192000,cy:6858000},{width:2000,height:1000})).toEqual({x:232,y:156,width:816,height:408})
 expect(imagePlacement({cx:12192000,cy:6858000},{width:100,height:50},{x:192,y:192})).toEqual({x:615,y:347.5,width:50,height:25})
})
it('拒绝伪装PNG以及超过预算的文件，不把文件名当身份',async()=>{
 await expect(prepareSlideImage(new File(['not png'],'image.png',{type:'image/png'}),{cx:12192000,cy:6858000})).rejects.toThrow('PNG 或 JPEG')
 await expect(prepareSlideImage(new File([new Uint8Array(6*1024*1024+1)],'large.png',{type:'image/png'}),{cx:12192000,cy:6858000})).rejects.toThrow('6 MiB')
})
