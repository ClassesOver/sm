import { afterEach, expect, it } from 'vitest'
import { createModal } from './modal'

const modals: ReturnType<typeof createModal>[] = []
afterEach(() => { modals.splice(0).forEach(modal => modal.remove()); document.body.replaceChildren() })
function fixture() {
  const trigger = document.body.appendChild(document.createElement('button'))
  const modal = createModal({ root: document.body, label: '设置', closeLabel: '关闭设置', content: '<label>标题<input aria-label="标题"></label>' })
  modals.push(modal)
  const input = modal.card.querySelector('input')!
  trigger.focus(); modal.open(input); input.value = '未提交的中文草稿'
  return { trigger, modal, input }
}

it.each([{ isComposing: true }, { keyCode: 229 }])('输入法组合期间的Escape保留弹窗、字段草稿和焦点：%j', composition => {
  const { modal, input } = fixture()
  const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, ...composition })
  input.dispatchEvent(event)
  expect(modal.overlay.hidden).toBe(false)
  expect(input.value).toBe('未提交的中文草稿')
  expect(document.activeElement).toBe(input)
  expect(event.defaultPrevented).toBe(false)
})

it('子控件已消费的Escape不再关闭父弹窗，下一次普通Escape仍可关闭', () => {
  const { trigger, modal, input } = fixture()
  input.addEventListener('keydown', event => event.preventDefault(), { once: true })
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(modal.overlay.hidden).toBe(false)
  expect(document.activeElement).toBe(input)
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(modal.overlay.hidden).toBe(true)
  expect(document.activeElement).toBe(trigger)
})

it('普通Escape走原关闭回调，忙碌时拒绝关闭的决定仍由调用方控制', () => {
  let busy = true, requests = 0
  const modal = createModal({ root: document.body, label: '设置', content: '<input aria-label="标题">', onRequestClose: () => { requests++; if (!busy) modal.close() } })
  modals.push(modal)
  modal.open()
  const input = modal.card.querySelector('input')!
  const escape = () => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  escape(); expect(requests).toBe(1); expect(modal.overlay.hidden).toBe(false)
  busy = false
  escape(); expect(requests).toBe(2); expect(modal.overlay.hidden).toBe(true)
  escape(); expect(requests).toBe(2)
})

it.each([true, false])('Escape只关闭最后打开的弹窗，与创建顺序和事件可取消性无关：%s', cancelable => {
  const trigger = document.body.appendChild(document.createElement('button'))
  const child = createModal({ root: document.body, label: '子设置', content: '<input aria-label="子字段">' })
  const parent = createModal({ root: document.body, label: '父设置', content: '<button>打开子设置</button>' })
  modals.push(child, parent)
  trigger.focus(); parent.open()
  const opener = parent.card.querySelector('button')!
  child.open()
  child.card.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable }))
  expect(child.overlay.hidden).toBe(true)
  expect(parent.overlay.hidden).toBe(false)
  expect(document.activeElement).toBe(opener)
  opener.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable }))
  expect(parent.overlay.hidden).toBe(true)
  expect(document.activeElement).toBe(trigger)
})

it('最上层忙碌时拒绝Escape不会向底层传递关闭请求', () => {
  const parent = createModal({ root: document.body, label: '父设置', content: '<button>打开</button>' })
  let requests = 0
  const child = createModal({ root: document.body, label: '忙碌设置', content: '<input>', onRequestClose: () => { requests++ } })
  modals.push(parent, child); parent.open(); child.open()
  child.card.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(requests).toBe(1)
  expect(parent.overlay.hidden).toBe(false)
  expect(child.overlay.hidden).toBe(false)
})

it('重复打开保留原触发入口，并使预先创建的弹窗位于同根最上层', () => {
  const { trigger, modal, input } = fixture()
  const other = createModal({ root: document.body, label: '另一个窗口', content: '<button>另一个</button>' })
  modals.push(other)
  other.open(); other.close()
  modal.open(input); modal.open(input)
  expect(document.body.lastElementChild).toBe(modal.overlay)
  modal.close()
  expect(document.activeElement).toBe(trigger)
})

it('移除底层窗口不会抢走顶层焦点，移除顶层时仍可回到有效入口', () => {
  const { trigger, modal } = fixture()
  const child = createModal({ root: document.body, label: '子设置', content: '<input>' })
  modals.push(child); trigger.focus(); child.open()
  const input = child.card.querySelector('input')!
  modal.remove()
  expect(document.activeElement).toBe(input)
  child.remove()
  expect(document.activeElement).toBe(trigger)
})

it('下层弹窗暂时退出键盘和读屏访问，关闭顶层后恢复', () => {
  const { modal } = fixture()
  const child = createModal({ root: document.body, label: '子设置', content: '<input>' })
  modals.push(child); child.open()
  expect(modal.overlay.inert).toBe(true)
  expect(modal.overlay.getAttribute('aria-modal')).toBe('false')
  expect(child.overlay.inert).toBe(false)
  expect(child.overlay.getAttribute('aria-modal')).toBe('true')
  child.close()
  expect(modal.overlay.inert).toBe(false)
  expect(modal.overlay.getAttribute('aria-modal')).toBe('true')
})

it.each(['close', 'remove'] as const)('顶层入口所在的底层窗口被%s后，继续回到原文档入口', method => {
  const { trigger, modal } = fixture()
  const child = createModal({ root: document.body, label: '子设置', content: '<input>' })
  modals.push(child); child.open()
  const input = child.card.querySelector('input')!
  modal[method]()
  expect(document.activeElement).toBe(input)
  child.close()
  expect(document.activeElement).toBe(trigger)
})

it('真正嵌套的弹窗不使包含它的祖先inert，底层遮罩也不能关闭窗口', () => {
  const { modal } = fixture()
  const child = createModal({ root: modal.card, label: '子设置', content: '<input>' })
  modals.push(child); child.open()
  expect(modal.overlay.inert).toBe(false)
  expect(modal.overlay.getAttribute('aria-modal')).toBe('false')
  modal.overlay.click()
  expect(modal.overlay.hidden).toBe(false)
  expect(child.overlay.hidden).toBe(false)
})

it('原生dialog中的Escape不关闭下面的自定义弹窗', () => {
  const { modal } = fixture()
  const dialog = document.body.appendChild(document.createElement('dialog'))
  dialog.setAttribute('open', '')
  const input = dialog.appendChild(document.createElement('input')); input.focus()
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(modal.overlay.hidden).toBe(false)
  expect(document.activeElement).toBe(input)
})

it('子弹窗在自身边界消费Escape，祖先面板不会先收到关闭按键', () => {
  const { modal } = fixture()
  const child = createModal({ root: modal.card, label: '子设置', content: '<input>' })
  modals.push(child)
  let ancestorRequests = 0
  modal.overlay.addEventListener('keydown', event => { if (event.key === 'Escape') ancestorRequests++ })
  child.open()
  child.card.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(ancestorRequests).toBe(0)
  expect(modal.overlay.hidden).toBe(false)
  expect(child.overlay.hidden).toBe(true)
})
