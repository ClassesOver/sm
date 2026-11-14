import {readFileSync} from 'node:fs'
import {expect,it} from 'vitest'
const source=readFileSync(process.env.PICTURE_MAIN_SOURCE ?? 'src/workbook-main.ts','utf8')
it('cancels the native picture command before delegating one validated batch to draft history',()=>{
 expect(source).toContain('captureWorkbookPictureEdits(command, workbook.getId(), pictureBindings')
 expect(source).toContain('pictureBindings = await installWorkbookPictures')
 expect(source).toContain('WORKBOOK_PICTURE_EDIT_WRAPPERS.some')
 expect(source).toContain('pictureEditBusy || saved || saving')
 expect(source).toContain('const additions = typeof operation')
 expect(source).not.toContain('普通图片暂不支持拖移或删除')
})
it('waits for native picture rendering and cancels stale selection restoration',()=>{
 expect(source).toContain("from './workbook-picture-selection'")
 expect(source).toContain('refreshTransform$: manager.refreshTransform$')
 const begin=source.indexOf('pictureSelection.start(identities')
 const activate=source.indexOf('active!.setActiveSheet(targetSheet)',begin)
 expect(begin).toBeGreaterThan(-1)
 expect(activate).toBeGreaterThan(begin)
 expect(source.slice(activate,activate+200)).toContain('manager.focusDrawing(identities)')
 expect(source.slice(activate,activate+200)).toContain('pictureSelection.check()')
 expect(source).toContain("shell.editor.addEventListener('pointerdown', cancelPictureSelection, true)")
 expect(source).toContain("shell.editor.removeEventListener('pointerdown', cancelPictureSelection, true)")
 expect(source).toContain('pictureSelection?.dispose(); pictureSelection = undefined')
})
