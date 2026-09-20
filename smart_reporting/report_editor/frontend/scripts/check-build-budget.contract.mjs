import assert from 'node:assert/strict'

import { checkBuildBudget } from './check-build-budget.mjs'

const ok = checkBuildBudget([
  { file: 'assets/index-example.js', size: 170 * 1024 },
  { file: 'assets/milkdown-example.js', size: 690 * 1024 },
  { file: 'assets/history.js', size: 20 * 1024 },
  { file: 'assets/plotly.min-example.js', size: 4802 * 1024 },
])
assert.deepEqual(ok, [])

const failures = checkBuildBudget([
  { file: 'assets/index-example.js', size: 181 * 1024 },
  { file: 'assets/milkdown-example.js', size: 701 * 1024 },
  { file: 'assets/history.js', size: 251 * 1024 },
  { file: 'assets/plotly.min-example.js', size: 5201 * 1024 },
])
assert.equal(failures.length, 4)
assert.match(failures[0], /index-example\.js/)
assert.match(failures[1], /milkdown-example\.js/)
assert.match(failures[2], /history\.js/)
assert.match(failures[3], /plotly\.min-example\.js/)
