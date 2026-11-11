import assert from 'node:assert/strict'

import { checkBuildBudget } from './check-build-budget.mjs'

const ok = checkBuildBudget([
  { file: 'assets/index-example.js', size: 170 * 1024 },
  { file: 'assets/milkdown-example.js', size: 690 * 1024 },
  { file: 'assets/history.js', size: 20 * 1024 },
])
assert.deepEqual(ok, [])

const failures = checkBuildBudget([
  { file: 'assets/index-example.js', size: 181 * 1024 },
  { file: 'assets/milkdown-example.js', size: 701 * 1024 },
  { file: 'assets/history.js', size: 251 * 1024 },
])
assert.equal(failures.length, 3)
assert.match(failures[0], /index-example\.js/)
assert.match(failures[1], /milkdown-example\.js/)
assert.match(failures[2], /history\.js/)

// Heavy grid packages are lazy workbook chunks with package-specific limits.
assert.deepEqual(checkBuildBudget([
  { file: 'assets/lazy-workbook-icons-hash1234.js', size: 269 * 1024 },
  { file: 'assets/workbook-sheets-ui-hash1234.js', size: 900 * 1024 },
  { file: 'assets/workbook-dictionary-hu-hash1234.js', size: 770 * 1024 },
]), [])
assert.equal(checkBuildBudget([
  { file: 'assets/lazy-workbook-icons-hash1234.js', size: 276 * 1024 },
]).length, 1)
assert.deepEqual(checkBuildBudget([
  { file: 'assets/lazy-workbook-main-hash1234.js', size: 252 * 1024 },
]), [])
assert.equal(checkBuildBudget([
  { file: 'assets/lazy-workbook-main-hash1234.js', size: 254 * 1024 },
]).length, 1)
assert.equal(checkBuildBudget([
  { file: 'assets/workbook-sheets-ui-hash1234.js', size: 911 * 1024 },
  { file: 'assets/workbook-arbitrary-hash1234.js', size: 251 * 1024 },
]).length, 2)

assert.deepEqual(checkBuildBudget([{file:"assets/lazy-index-hash1234.js",size:240*1024}]),[])

assert.deepEqual(checkBuildBudget([
  {file:'assets/lazy-native-docx-engine-hash1234.js',size:419*1024},
  {file:'assets/lazy-native-docx-render-hash1234.js',size:709*1024},
  {file:'assets/lazy-native-pdfjs-hash1234.js',size:499*1024},
  {file:'assets/parse-worker-hash1234.js',size:699*1024},
]), [])
assert.deepEqual(checkBuildBudget([
  {file:'assets/lazy-react-hash1234.js',size:100*1024},
  {file:'assets/lazy-react-dom-hash1234.js',size:200*1024},
  {file:'assets/lazy-scheduler-hash1234.js',size:30*1024},
]), [])
assert.equal(checkBuildBudget([
  {file:'assets/lazy-native-docx-render-hash1234.js',size:711*1024},
  {file:'assets/lazy-native-arbitrary-hash1234.js',size:251*1024},
  {file:'assets/index-hash1234.js',size:181*1024},
]).length,3)
