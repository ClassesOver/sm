// 兼容旧快照的原始诊断；只解释展示含义，不改写冻结事实或核对状态。
const FIELD_LABELS: Record<string, string> = {
  company: '医院', area: '院区', stlevel_analytic_unit: '一级科室',
  rdlevel_analytic_unit: '三级科室', income_type: '收入类型',
  analytic_unit_classification: '科室分类', income_nature: '收入性质',
}

type Note = { text: string; type?: string }

export function renderEvidenceNotes(notes: readonly string[]): HTMLElement | null {
  if (!notes.length) return null
  const warnings: Note[] = []
  const context: Note[] = []
  const methods: Note[] = []
  const correlatedFields = new Set<string>()
  const originals = [...new Set(notes)]
  for (const note of originals) {
    if (note === '期间索引存在重复，行级 ACF/PACF 和季节性统计已禁用；需先按月及组织粒度聚合。') {
      methods.push({ text: '同一期间有多条明细，不等同于重复记录。行级自相关和季节性统计未执行；需先按月及目标组织粒度聚合，并检查时间序列的连续性和期间长度，再判断是否适合分析。' })
      continue
    }
    if (note === '[company] has a constant value') {
      context.push({ text: '医院字段只有一个取值，本数据集不支持院际比较；这本身不代表数据异常。' })
      continue
    }
    const scope = /^固定范围 (\w+)=(.+) 已由受审核 SQL 应用，CSV 未投影该范围字段。$/.exec(note)
    if (scope) {
      context.push({ text: `查询口径：${FIELD_LABELS[scope[1]] ?? scope[1]}=${scope[2]}。登记信息表明筛选已在取数时应用，明细未重复输出该字段。` })
      continue
    }
    const correlation = /^\[\w+\] is highly overall correlated with \[\w+\](?: and \d+ other fields)?$/.test(note)
    const fields = [...note.matchAll(/\[(\w+)\]/g)].map(match => match[1])
    if (correlation && fields.every(field => Object.hasOwn(FIELD_LABELS, field))) {
      fields.forEach(field => correlatedFields.add(FIELD_LABELS[field]))
      continue
    }
    const imbalance = /^\[(\w+)\] is highly imbalanced \(([\d.eE+-]+)\)$/.exec(note)
    if (imbalance && Object.hasOwn(FIELD_LABELS, imbalance[1])) {
      context.push({ text: `${FIELD_LABELS[imbalance[1]]}分布集中，比较不同类别时需考虑样本量差异。原始不均衡指标不等同于某一类别的占比。` })
      continue
    }
    const missing = /^\[(\w+)\] (\d+) \(([\d.]+)%\) missing values$/.exec(note)
    if (missing) {
      const label = FIELD_LABELS[missing[1]] ?? missing[1]
      const impact = missing[1] === 'rdlevel_analytic_unit'
        ? '三级科室下钻与归属分析受限；汇总需保留未归属记录，不能直接丢弃。'
        : '使用该字段分组或分析前，需确认缺失记录的处理方式。'
      warnings.push({ text: `${label}缺失 ${Number(missing[2]).toLocaleString('en-US')} 条（${missing[3]}%）。${impact}` })
      continue
    }
    // 未识别的提示保持为告警，不能因翻译或分类失败而静默丢弃。
    warnings.push({ text: note })
  }
  if (correlatedFields.size) context.push({
    type: 'correlation',
    text: `检测到${[...correlatedFields].join('、')}等维度的分布关联。这本身不代表数据错误或因果关系；交叉比较时需核对组织层级与统计范围。`,
  })

  const root = document.createElement('div')
  root.className = 'evidence-notes'
  const append = (kind: string, title: string, items: Note[], open = false) => {
    if (!items.length) return
    const group = document.createElement('details')
    group.dataset.noteKind = kind
    group.className = kind === 'warnings' ? 'evidence-limitations' : 'evidence-note-info'
    group.open = open
    const summary = document.createElement('summary')
    summary.className = 'evidence-limitations-title'
    summary.textContent = `${title}（${items.length}）`
    group.append(summary)
    for (const item of items) {
      const paragraph = document.createElement('p')
      paragraph.className = 'evidence-limitation'
      if (item.type) paragraph.dataset.noteType = item.type
      paragraph.textContent = item.text
      group.append(paragraph)
    }
    root.append(group)
  }
  append('warnings', '数据限制', warnings, true)
  append('method', '分析方法限制', methods)
  append('context', '数据口径与分布特征', context)
  append('raw', '原始诊断', originals.map(text => ({ text })))
  return root
}
