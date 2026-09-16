import { installFocusTrap } from './focus-trap'

const HOSPITAL_OPERATIONS_TEMPLATE = `# 医院整体运营情况分析报告

> 报告周期：____年__月__日 - ____年__月__日

## 核心结论

概述本期医院运营表现、主要变化和需要管理层关注的事项。

## 关键指标

| 指标 | 本期 | 同比 | 状态 |
| --- | ---: | ---: | --- |
| 门急诊人次 |  |  |  |
| 出院人次 |  |  |  |
| 平均住院日 |  |  |  |
| 床位使用率 |  |  |  |

## 医疗服务运行

### 门急诊服务

补充服务量、峰值时段和患者等候情况。

### 住院服务

补充床位效率、病种结构和重点科室情况。

## 经营效率分析

补充收入结构、成本效率和医保结算情况。

## 医疗质量与患者体验

补充质量安全、服务体验和重点改进指标。

## 风险与建议

1. 
2. 
3. 
`

const RISK_SECTION = `## 风险与建议

1. **重点风险：** 描述风险、影响范围和判断依据。
2. **改进措施：** 明确责任部门、完成时限和衡量指标。
3. **跟踪机制：** 说明复盘频率和升级条件。
`

export function createTemplatePanel(
  root: HTMLElement,
  getMarkdown: () => string,
  apply: (markdown: string) => void,
) {
  const dialog = document.createElement('div')
  dialog.className = 'template-panel'
  dialog.hidden = true
  dialog.innerHTML = `
    <section class="template-card" role="dialog" aria-modal="true" aria-labelledby="template-title">
      <button type="button" class="template-close" aria-label="关闭模板">×</button>
      <h2 id="template-title">报告模板</h2>
      <p>选择完整模板或追加常用章节。</p>
      <div class="template-list">
        <button type="button" data-template="hospital-operations"><strong>医院整体运营报告</strong><span>替换为完整的运营分析结构</span></button>
        <button type="button" data-template="risk-section"><strong>风险与建议</strong><span>追加风险、措施和跟踪机制</span></button>
      </div>
    </section>
  `
  root.append(dialog)
  installFocusTrap(dialog)
  let opener: HTMLElement | null = null
  const close = () => {
    dialog.hidden = true
    opener?.focus()
    opener = null
  }
  dialog.querySelector<HTMLButtonElement>('.template-close')!.addEventListener('click', close)
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) close()
  })
  dialog.querySelector<HTMLButtonElement>('[data-template="hospital-operations"]')!
    .addEventListener('click', () => {
      if (getMarkdown().trim() && !window.confirm('应用完整模板将替换当前草稿，是否继续？')) return
      apply(HOSPITAL_OPERATIONS_TEMPLATE)
      close()
    })
  dialog.querySelector<HTMLButtonElement>('[data-template="risk-section"]')!
    .addEventListener('click', () => {
      apply(`${getMarkdown().trimEnd()}\n\n${RISK_SECTION}`)
      close()
    })
  return {
    dialog,
    open() {
      opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
      dialog.hidden = false
      dialog.querySelector<HTMLButtonElement>('[data-template]')?.focus()
    },
  }
}
