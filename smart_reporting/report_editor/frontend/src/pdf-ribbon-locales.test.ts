import { expect, it } from 'vitest'
import { pdfRibbonLabel } from './pdf-ribbon-locales'

it('PDF AI 和编辑功能组在中文功能区完整翻译且保留英文切换', () => {
  const groups = {'AI':'AI 助手','AI Review':'AI 审阅','Draw Tools':'绘图工具','Edit':'编辑','Convert & Export':'转换与导出','Search, Print & Properties':'搜索、打印与属性','Signature & Protection':'签名与保护'}
  for(const [key,label] of Object.entries(groups)) {
    expect(pdfRibbonLabel(key,'zh-CN')).toBe(label)
    expect(pdfRibbonLabel(key,'en')).toBe(key)
  }
})
