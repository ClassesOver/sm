import { describe, expect, it } from 'vitest'

import { createBlankWorkbook } from '../src/blank'
import { applyCfRules } from '../src/rules'
import { readWorkbook } from '../src/workbook-read'

describe('conditional format read-back (grid render bridge)', () => {
  it('reads dataBar and colorScale rules back out of the model', async () => {
    const bytes = await createBlankWorkbook()
    const seeded = await applyCfRules(bytes, [
      {
        kind: 'dataBar', sheet: 'Sheet1', sqref: 'B2:B4',
        min: { type: 'num', value: 0 }, max: { type: 'num', value: 100 },
        color: '#2f9e6e',
      },
      {
        kind: 'colorScale', sheet: 'Sheet1', sqref: 'C2:C5',
        stops: [
          { cfvo: { type: 'min' }, color: '#F8696B' },
          { cfvo: { type: 'percentile', value: 50 }, color: '#FFEB84' },
          { cfvo: { type: 'max' }, color: '#63BE7B' },
        ],
      },
    ])
    const model = await readWorkbook(seeded)
    const rules = model.sheets[0]?.conditionalFormats ?? []
    expect(rules).toHaveLength(2)

    const bar = rules.find((rule) => rule.kind === 'dataBar')
    expect(bar).toMatchObject({
      kind: 'dataBar', sheet: 'Sheet1', sqref: 'B2:B4',
      min: { type: 'num', value: 0 }, max: { type: 'num', value: 100 },
      color: '#2F9E6E',
    })
    const scale = rules.find((rule) => rule.kind === 'colorScale')
    expect(scale).toMatchObject({
      kind: 'colorScale', sheet: 'Sheet1', sqref: 'C2:C5',
    })
    expect(scale?.kind === 'colorScale' && scale.stops.map((stop) => stop.color)).toEqual(
      ['#F8696B', '#FFEB84', '#63BE7B'],
    )
  })

  it('replays a read-back rule to the identical package state', async () => {
    const bytes = await createBlankWorkbook()
    const rule = {
      kind: 'dataBar' as const, sheet: 'Sheet1', sqref: 'B2:B3',
      min: { type: 'min' as const }, max: { type: 'max' as const },
      color: '#638EC6',
    }
    const once = await applyCfRules(bytes, [rule])
    const read = ((await readWorkbook(once)).sheets[0]?.conditionalFormats ?? [])[0]
    expect(read).toEqual(rule)
    // applyCfRules appends, so replay onto the original blank and compare:
    // the read-back rule must reproduce the exact same package state
    const replayed = await applyCfRules(bytes, [read!])
    expect(await readWorkbook(replayed)).toEqual(await readWorkbook(once))
  })
})
