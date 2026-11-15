/** GenOffice f8c17004 workbook-search.ts buildMatcher, adapted to JSON stdin.
 * Upstream: genspark-ai/genoffice, Apache-2.0. License and NOTICE:
 * frontend/src/vendor/genoffice-docs/{LICENSE,NOTICE}.
 * Keep JavaScript RegExp/lowercase/scalar conversion semantics in the Node host.
 * The Python caller supplies only authorized frozen cells and enforces a timeout.
 */
import { readFileSync } from 'node:fs'

const { cells, query, regex, look_in, errors_only, max_results } = JSON.parse(readFileSync(0, 'utf8'))
const errorValue = /^#(?:REF!|DIV\/0!|VALUE!|NAME\?|N\/A|NUM!|NULL!|SPILL!|CALC!|FIELD!|CONNECT!|BLOCKED!|UNKNOWN!|GETTING_DATA)$/
let matchText
try {
  if (!errors_only) {
    if (regex) {
      const pattern = new RegExp(query, 'i')
      matchText = text => pattern.test(text)
    } else {
      const needle = query.toLowerCase()
      matchText = text => text.toLowerCase().includes(needle)
    }
  }
} catch {
  process.stdout.write(JSON.stringify({ error: 'invalid_regex' }))
  process.exit(0)
}
const indexes = []
let truncated = false
for (let index = 0; index < cells.length; index++) {
  const { value, formula } = cells[index]
  const matches = errors_only
    ? typeof value === 'string' && errorValue.test(value)
    : (look_in !== 'formulas' && value != null &&
        matchText(typeof value === 'boolean' ? (value ? '1' : '0') : String(value))) ||
      (look_in !== 'values' && Boolean(formula) && matchText(formula))
  if (!matches) continue
  if (indexes.length === max_results) {
    truncated = true
    break
  }
  indexes.push(index)
}
process.stdout.write(JSON.stringify({ indexes, truncated }))
