import {afterEach, expect, it, vi} from 'vitest'
import {openInlineFolder} from './office-inline-folder'

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
