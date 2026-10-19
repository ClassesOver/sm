import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { Schema } from '@milkdown/kit/prose/model'
import { Plugin, EditorState } from '@milkdown/kit/prose/state'
import { EditorView } from '@milkdown/kit/prose/view'
import { beforeAll, expect, it } from 'vitest'

import type { TraceValidation } from './api'
import { createBodyValueMarksPlugin, documentValueMarks, restoreRegisteredValue, updateBodyValueMarks } from './body-value-marks'
import { markerDecorations } from './protocol-plugin'
import { nextSourceIssue, sourceCoverageSummary, sourceValidationIssueCount } from './source-validation'

interface ReviewCase {
  id: string; marks: string[]; issues: number; warning?: string; original?: string; canRestore?: boolean
}
const cases: ReviewCase[] = JSON.parse(readFileSync(resolve(
  '../../reporting/tests/fixtures/reference_review_cases.json',
), 'utf8')).cases
const artifacts = process.env.REFERENCE_REVIEW_HARNESS_OUTPUT
const schema = new Schema({ nodes: {
  doc: { content: 'paragraph+' }, paragraph: { content: 'text*', toDOM: () => ['p', 0] }, text: {},
} })

beforeAll(() => {
  if (!artifacts) return
  // 每次运行必须消费本次后端实际生成的完整结果，不能沿用上次留下的部分文件。
  expect(readdirSync(artifacts).filter(name => name.endsWith('.json')).sort())
    .toEqual(cases.map(item => `${item.id}.json`).sort())
})

for (const example of cases) {
  it.skipIf(!artifacts)(`API → editor → navigation: ${example.id}`, () => {
    const replay: { case: ReviewCase; markdown: string; validation: TraceValidation;
      restored?: { markdown: string; validation: TraceValidation } | null } = JSON.parse(
      readFileSync(join(artifacts!, `${example.id}.json`), 'utf8'),
    )
    expect(replay.case).toMatchObject(example)
    const host = document.createElement('div')
    document.body.append(host)
    const view = new EditorView(host, { state: EditorState.create({
      schema, doc: schema.node('doc', null, [schema.node('paragraph', null, schema.text(replay.markdown))]),
      plugins: [createBodyValueMarksPlugin(), new Plugin({ props: { decorations: state => markerDecorations(state.doc) } })],
    }) })
    try {
      const validation = replay.validation
      updateBodyValueMarks(view, validation)
      const marks = documentValueMarks(view.state.doc, validation)
      expect(marks.map(mark => mark.state)).toEqual(example.marks)
      expect(sourceValidationIssueCount(validation)).toBe(example.issues)
      if (example.warning) expect(marks.flatMap(mark => mark.card).join('\n')).toContain(example.warning)
      if (example.original) {
        expect(view.dom.querySelector('.report-original-value')?.textContent).toContain(example.original)
        expect(view.state.doc.textContent).not.toContain(example.original)
      }
      const actionable = marks.filter(mark => mark.state !== 'valid')
      const coverage = sourceCoverageSummary(validation, view.state.doc.textContent)
      expect(coverage.state).toBe(actionable.length ? 'stale' : 'valid')
      let after: number | null = null
      const visited: number[] = []
      for (let index = 0; index < actionable.length; index++) {
        const target = nextSourceIssue(view.dom, after, element => view.posAtDOM(element, 0), validation)
        expect(target).not.toBeNull()
        expect(target!.classList.contains('report-original-value')).toBe(false)
        after = view.posAtDOM(target!, 0)
        visited.push(after)
      }
      expect(new Set(visited).size).toBe(actionable.length)
      const next = nextSourceIssue(view.dom, after, element => view.posAtDOM(element, 0), validation)
      if (visited.length) expect(view.posAtDOM(next!, 0)).toBe(visited[0])
      else expect(next).toBeNull()
      const before = view.state.doc
      expect(restoreRegisteredValue(view, validation.subjects[0].subjectId, validation)).toBe(example.canRestore ?? false)
      expect(view.state.doc.eq(before)).toBe(!example.canRestore)
      if (example.canRestore) {
        expect(replay.restored).toBeTruthy()
        // 实际写回正文必须与后端再次校验通过的正文逐字相同，才能消除待复核状态。
        expect(view.state.doc.textContent).toBe(replay.restored!.markdown)
        updateBodyValueMarks(view, replay.restored!.validation)
        expect(documentValueMarks(view.state.doc, replay.restored!.validation).every(mark => mark.state === 'valid')).toBe(true)
        expect(sourceCoverageSummary(replay.restored!.validation, view.state.doc.textContent).state).toBe('valid')
        expect(nextSourceIssue(view.dom, null, element => view.posAtDOM(element, 0), replay.restored!.validation)).toBeNull()
      }
    } finally {
      view.destroy()
      host.remove()
    }
  })
}
