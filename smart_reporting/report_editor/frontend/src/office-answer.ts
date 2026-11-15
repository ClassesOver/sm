import './office-answer.css'
import { copyText } from './clipboard'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Markdown } from './vendor/genoffice-ai-panel/Markdown'

export function renderOfficeAnswer(text: string) {
  return renderToStaticMarkup(createElement(Markdown, { text }))
}


export function showOfficeAnswer(output: HTMLElement, text: string, allowCopy = false) {
  output.innerHTML = renderOfficeAnswer(text)
  if (!allowCopy) return
  const copy = document.createElement('button')
  copy.type = 'button'
  copy.textContent = '复制回答'
  copy.setAttribute('aria-label', '复制回答')
  copy.onclick = async () => {
    try {
      await copyText(text)
      copy.textContent = '已复制'
    } catch {
      copy.textContent = '复制失败，请重试'
    }
  }
  output.append(copy)
}


export function appendOfficeAnswer(
  transcript: HTMLElement, question: string, answer: string, allowCopy = false,
) {
  const turn = document.createElement('article')
  const prompt = document.createElement('p')
  prompt.className = 'native-ai-question'
  prompt.textContent = question
  const output = document.createElement('div')
  output.className = 'native-ai-answer'
  const evidence = document.createElement('div')
  evidence.className = 'native-ai-evidence'
  showOfficeAnswer(output, answer, allowCopy)
  turn.append(prompt, output, evidence)
  transcript.append(turn)
  return evidence
}
