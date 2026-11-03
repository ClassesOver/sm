import { describe, expect, it } from 'vitest'

import {
  PivotFormulaError,
  evaluatePivotFormula,
  formatPivotFormula,
  parsePivotFormula,
} from '../src/pivot-formula'

const FIELDS = ['Sales', 'Cost', '数量']

describe('pivot calculated-field formulas', () => {
  it('parses arithmetic with precedence, parens, and unary minus', () => {
    expect(formatPivotFormula(parsePivotFormula('Sales*2', FIELDS))).toBe("('Sales'*2)")
    expect(formatPivotFormula(parsePivotFormula('Sales - Cost', FIELDS))).toBe("('Sales'-'Cost')")
    expect(formatPivotFormula(parsePivotFormula('(Sales+Cost)/2', FIELDS))).toBe(
      "(('Sales'+'Cost')/2)",
    )
    expect(formatPivotFormula(parsePivotFormula('-Sales + 3', FIELDS))).toBe("((-'Sales')+3)")
    // field references normalize case-insensitively to the canonical names
    expect(formatPivotFormula(parsePivotFormula('sales', FIELDS))).toBe("'Sales'")
    // CJK and quoted names round-trip; '' escapes an inner quote
    expect(formatPivotFormula(parsePivotFormula("'数量' * 2", FIELDS))).toBe("('数量'*2)")
  })

  it('runs the AST interpreter safely (division by zero → null)', () => {
    const ast = parsePivotFormula('Sales / Cost', FIELDS)
    expect(evaluatePivotFormula(ast, (name) => (name === 'Sales' ? 10 : 2))).toBe(5)
    expect(evaluatePivotFormula(ast, (name) => (name === 'Sales' ? 10 : 0))).toBeNull()
    // field references with no aggregatable value count as 0
    expect(evaluatePivotFormula(parsePivotFormula('Sales+10', FIELDS), () => null)).toBe(10)
  })

  it('fails closed on unknown fields, unbalanced input, and bad tokens', () => {
    expect(() => parsePivotFormula('Profit', FIELDS)).toThrow(PivotFormulaError)
    expect(() => parsePivotFormula('(Sales', FIELDS)).toThrow(/ended unexpectedly/)
    expect(() => parsePivotFormula('Sales)', FIELDS)).toThrow(/parsed further/)
    expect(() => parsePivotFormula("''", FIELDS)).toThrow(/empty field name/)
    expect(() => parsePivotFormula("'Sales", FIELDS)).toThrow(/Unclosed quote/)
    // '@' lexes as a bare-name field, so the parse stops right after 'Sales'
    expect(() => parsePivotFormula('Sales @ Cost', FIELDS)).toThrow(/parsed further/)
  })
})
