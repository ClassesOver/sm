// @vitest-environment node
import {expect,it} from 'vitest'
import config from '../vite.config'

it('keeps the eager zoom draft validator separate from thumbnail UI dependencies',()=>{
 const output=config.build!.rollupOptions!.output as {manualChunks:(id:string)=>string|undefined}
 const model=output.manualChunks('/workspace/frontend/src/slides-zoom-model.ts')
 const grid=output.manualChunks('/workspace/frontend/src/slides-zoom-grid.tsx')
 expect(model).not.toBe(grid)
})
