import {afterEach, expect, it, vi} from 'vitest'
import {openInlineFolder, renameInlineFolder} from './office-inline-folder'

afterEach(() => document.body.replaceChildren())

function setup() {
  const parent = document.body.appendChild(document.createElement('div'))
  parent.style.setProperty('--depth', '2')
  const create = vi.fn()
  const input = openInlineFolder(parent, create)
  return {parent, create, input}
}

it('focuses a child row and commits only once with Enter and blur', () => {
  const {parent, create, input} = setup()
  expect(document.activeElement).toBe(input)
  expect(input.parentElement?.previousElementSibling).toBe(parent)
  expect(input.parentElement?.style.getPropertyValue('--depth')).toBe('3')
  input.value = ' 合同 '
  input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter'}))
  input.dispatchEvent(new FocusEvent('blur'))
  expect(create).toHaveBeenCalledExactlyOnceWith('合同')
  expect(input.isConnected).toBe(false)
})

it('ignores Enter during composition and Escape cancels without creating', () => {
  const {create, input} = setup()
  input.value = '合同'
  input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', isComposing: true}))
  expect(input.isConnected).toBe(true)
  input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))
  input.dispatchEvent(new FocusEvent('blur'))
  expect(create).not.toHaveBeenCalled()
})

it('dismisses a blank name on blur', () => {
  const {create, input} = setup()
  input.value = ' '
  input.dispatchEvent(new FocusEvent('blur'))
  expect(create).not.toHaveBeenCalled()
})

it('renames in the existing row and restores the original control when cancelled', () => {
  const row = document.body.appendChild(document.createElement('div'))
  const button = row.appendChild(document.createElement('button'))
  button.textContent = '草稿'
  const rename = vi.fn()
  let input = renameInlineFolder(button, '草稿', rename)
  expect(input.parentElement).toBe(row)
  expect(input.value).toBe('草稿')
  expect(document.activeElement).toBe(input)
  input.value = '取消'
  input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))
  expect(row.firstElementChild).toBe(button)
  expect(document.activeElement).toBe(button)
  expect(rename).not.toHaveBeenCalled()
  input = renameInlineFolder(button, '草稿', rename)
  input.value = ' 定稿 '
  input.dispatchEvent(new FocusEvent('blur'))
  expect(rename).toHaveBeenCalledExactlyOnceWith('定稿')
})

it('does not submit a rename when the trimmed name is unchanged', () => {
  const button = document.body.appendChild(document.createElement('button'))
  const rename = vi.fn()
  const input = renameInlineFolder(button, '草稿', rename)
  input.value = ' 草稿 '
  input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter'}))
  expect(rename).not.toHaveBeenCalled()
})
