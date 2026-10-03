import assert from 'node:assert/strict'

import { checkBuildBudget } from './check-build-budget.mjs'

const ok = checkBuildBudget([
  { file: 'assets/index-example.js', size: 170 * 1024 },
  { file: 'assets/milkdown-example.js', size: 690 * 1024 },
  { file: 'assets/history.js', size: 20 * 1024 },
  { file: 'assets/plotly.min-example.js', size: 4802 * 1024 },
  { file: 'assets/3d-force-graph-example.js', size: 1500 * 1024 },
  { file: 'assets/three.module-example.js', size: 640 * 1024 },
])
assert.deepEqual(ok, [])

const failures = checkBuildBudget([
  { file: 'assets/index-example.js', size: 181 * 1024 },
  { file: 'assets/milkdown-example.js', size: 701 * 1024 },
  { file: 'assets/history.js', size: 251 * 1024 },
  { file: 'assets/plotly.min-example.js', size: 5201 * 1024 },
  { file: 'assets/3d-force-graph-example.js', size: 1601 * 1024 },
  { file: 'assets/three.module-example.js', size: 651 * 1024 },
])
assert.equal(failures.length, 6)
assert.match(failures[0], /index-example\.js/)
assert.match(failures[1], /milkdown-example\.js/)
assert.match(failures[2], /history\.js/)
assert.match(failures[3], /plotly\.min-example\.js/)
assert.match(failures[4], /3d-force-graph-example\.js/)
assert.match(failures[5], /three\.module-example\.js/)
