import { describe, expect, it } from 'vitest'
import { patchSlideHiddenXml, readSlideHiddenXml } from '../src/generate'

describe('隐藏页原生布尔属性兼容', () => {
  it.each(['show="0"', 'show="false"', "show='0'", "show='false'"])(
    '读取并切换合法隐藏属性 %s，保留其他页属性', flag => {
      const prefix = '<p:sld xmlns:p="p" showMasterSp=\'0\' ' + flag + ' showMasterPhAnim="1"><p:cSld>'
      expect(readSlideHiddenXml(prefix)).toBe(true)
      const shown = patchSlideHiddenXml(prefix, false)
      expect(shown).toBe('<p:sld xmlns:p="p" showMasterSp=\'0\' showMasterPhAnim="1"><p:cSld>')
      expect(readSlideHiddenXml(shown)).toBe(false)
      const hidden = patchSlideHiddenXml(prefix, true)
      expect(readSlideHiddenXml(hidden)).toBe(true)
      expect(hidden.match(/\sshow=/g)).toHaveLength(1)
      expect(patchSlideHiddenXml(hidden, true)).toBe(hidden)
      expect(patchSlideHiddenXml(hidden, false)).toBe(shown)
    },
  )
  it.each(['', ' show="1"', ' show="true"', " show='1'", " show='true'"])(
    '默认及显式显示属性保持可见 %s', flag => {
      expect(readSlideHiddenXml('<p:sld' + flag + '><p:cSld>')).toBe(false)
    },
  )
})
