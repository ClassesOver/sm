// Only selectors change; source declarations and comments remain intact.
const fs = require('node:fs')
const path = require('node:path')
const postcss = require('postcss')
const root = postcss.parse(fs.readFileSync(path.join(__dirname, 'ribbon.source.css'), 'utf8'))
const prefix = '.slides-native-ribbon.slides-native-ribbon.slides-native-ribbon'
root.walkRules(rule => {
  if (rule.parent.type === 'atrule' && rule.parent.name.includes('keyframes')) return
  rule.selector = rule.selectors.map(selector => selector === '.ribbon' ? prefix + selector : prefix + ' ' + selector).join(',\n')
})
fs.writeFileSync(path.join(__dirname, 'ribbon.scoped.css'), root.toString())
