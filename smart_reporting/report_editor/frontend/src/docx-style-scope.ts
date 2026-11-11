/** 文档动态样式与vendor静态样式使用相同宿主作用域；由浏览器CSSOM区分选择器与at-rule。 */
export function scopeDocxStyleRules(sheet: CSSStyleSheet) {
  const scope = (rules: CSSRuleList) => {
    for (const rule of rules) {
      if (rule.type === CSSRule.STYLE_RULE) {
        const style = rule as CSSStyleRule
        style.selectorText = style.selectorText.replace(/\.doc-page\b/g, '.docx-native .doc-page')
      } else if ('cssRules' in rule) scope((rule as CSSGroupingRule).cssRules)
    }
  }
  scope(sheet.cssRules)
}
