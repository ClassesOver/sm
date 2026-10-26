import type { EditorView } from '@milkdown/kit/prose/view'
import type { Node as ProseMirrorNode } from '@milkdown/kit/prose/model'
import { buttonClasses } from './button'
import { createModal } from './modal'
import type { ChartAIEditSuccess, ReportEditorClient, TraceChartInfo } from './api'

/** 设计稿：docs/superpowers/specs/2026-10-25-report-editor-ai-chart-edit-design.md §3/§10。 */

const UNAVAILABLE_REASONS: Record<string, string> = {
  read_only: '当前会话为只读分享会话，不能使用 AI 改图。',
  unconfigured: 'AI 改图服务未配置完成。',
  vision_missing: '未配置视觉审查模型，AI 改图不可用。',
  snapshot_expired: '该版本的数据来源已结束保留期，AI 改图不可用。',
  plot_data_missing: '这张图没有登记作图数据（或来自旧报告），暂不支持改图。',
  unknown_chart: '图表不在当前版本的登记中。',
  unavailable: 'AI 改图当前不可用。',
}

const STAGE_LABELS: Record<string, string> = {
  queued: '排队中…',
  plan: '正在理解改图要求…',
  materialize: '正在准备作图数据…',
  draw: '正在绘图（通常 1–3 分钟）…',
  inspect: '正在检查图表…',
  register: '正在登记改图结果…',
}

const QUICK_COMMANDS = [
  '改成横向条形图并按数值降序排列',
  '在图上显示数值标签',
  '只保留金额最大的前 5 组，其余合并为“其他”并标注为子集',
  '把标题改得更简洁',
  '调整配色，提高对比度',
  '图例移到图表下方',
]

// P3：快捷指令按图形推荐——已知当前形态时优先给出“从该形态出发”的常用调整，
// 形态未知（未改图的原始图）回落到默认指令集。
const QUICK_COMMANDS_BY_FORM: [RegExp, string[]][] = [
  [/条形|柱状/, ['在图上显示数值标签', '按数值降序重新排列', '改成横向条形图', '只保留金额最大的前 5 组，其余合并为“其他”并标注为子集']],
  [/折线|趋势/, ['标注最高和最低的月份', '平滑折线并加粗', '改成柱状图对比各期', '在图上显示数值标签']],
  [/饼|构成|占比/, ['按占比从大到小排序', '只保留占比最大的前 5 项，其余合并为“其他”并标注为子集', '改成排序条形图', '在扇区外侧显示百分比']],
]

export function quickCommandsForForm(visualForm?: string | null): string[] {
  if (!visualForm) return QUICK_COMMANDS
  for (const [pattern, commands] of QUICK_COMMANDS_BY_FORM) {
    if (pattern.test(visualForm)) return [...new Set([...commands, ...QUICK_COMMANDS])].slice(0, QUICK_COMMANDS.length)
  }
  return QUICK_COMMANDS
}

const MAX_INSTRUCTION_CHARS = 2000

export function chartAiUnavailableReason(reason?: string): string {
  if (!reason) return UNAVAILABLE_REASONS.unavailable
  return UNAVAILABLE_REASONS[reason] ?? UNAVAILABLE_REASONS.unavailable
}

export function assetUrl(basePath: string, imagePath: string): string {
  const encoded = imagePath.split('/').map(encodeURIComponent).join('/')
  return `${basePath}/asset/${encoded}`
}

/** 从编辑器图片 src 提取登记的工作区相对路径（asset URL 形态时解码还原）。 */
export function workspacePathFromSrc(src: string, basePath: string): string | null {
  const marker = `${basePath.replace(/\/$/, '')}/asset/`
  const index = src.indexOf(marker)
  if (index < 0) return null
  const raw = src.slice(index + marker.length).split(/[?#]/)[0] ?? ''
  try {
    return raw.split('/').map(decodeURIComponent).join('/')
  } catch {
    return null
  }
}

/** 正文图片 → 登记图表：与后端 _manifest_image 同一“后缀唯一匹配”规则。 */
export function matchChartForImage(
  charts: TraceChartInfo[],
  src: string,
  basePath = '',
): TraceChartInfo | null {
  const candidates = [src.replace(/\\/g, '/'), workspacePathFromSrc(src, basePath) ?? '']
  const matches = charts.filter(chart => {
    const path = chart.imagePath.replace(/\\/g, '/')
    return candidates.some(value =>
      value &&
      !value.startsWith('/') &&
      !value.split('/').includes('..') &&
      (path === value || path.endsWith(`/${value}`)),
    )
  })
  return matches.length === 1 ? matches[0] : null
}

/** 正文图片已是 AI 改图结果（chart-edits/<editId>/chart.png）时返回 editId。 */
export function chartEditIdFromSrc(src: string, basePath = ''): string | null {
  const candidates = [src.replace(/\\/g, '/'), workspacePathFromSrc(src, basePath) ?? '']
  for (const value of candidates) {
    const matched = /(?:^|\/)chart-edits\/(cedit-[0-9a-z]{8,32})\/[^/]+$/.exec(value)
    if (matched) return matched[1]
  }
  return null
}

interface CaptionTarget {
  from: number
  to: number
  prefix: string
}

/** 图片块后紧跟的“图表：/图注：”段落；替换图注时一并写回，与图片同一次事务。 */
export function findChartCaptionParagraph(doc: ProseMirrorNode, posAfter: number): CaptionTarget | null {
  const node: ProseMirrorNode | undefined | null = doc.nodeAt(posAfter)
  if (!node || !node.isTextblock) return null
  const text = node.textContent ?? ''
  const matched = /^(图表|图注)\s*[:：]/.exec(text.trim())
  if (!matched) return null
  return { from: posAfter, to: posAfter + node.nodeSize, prefix: matched[0] }
}

const isImageNode = (node: ProseMirrorNode | null | undefined): node is ProseMirrorNode =>
  !!node && (node.type.name === 'image' || node.type.name === 'image-block')

/** 图片节点位置；行内图片（与引用标记同段）的图注段落在所在段落之后。 */
function locateImage(view: EditorView, img: HTMLImageElement) {
  const doc = view.state.doc
  const pos = view.posAtDOM(img, 0)
  const direct = doc.nodeAt(pos)
  if (isImageNode(direct)) {
    const blockEnd = direct.isInline ? doc.resolve(pos).after() : pos + direct.nodeSize
    return { from: pos, node: direct, blockEnd }
  }
  const resolved = doc.resolve(pos)
  if (!resolved.depth) return null
  const from = resolved.before()
  const node = doc.nodeAt(from)
  return isImageNode(node) ? { from, node, blockEnd: from + node.nodeSize } : null
}

export interface ChartReplacementText {
  title: string | null
  altText: string | null
}

/**
 * 接受替换：一次事务修改图片节点（src 与替代文本）与随后的“图表：/图注：”段落，保证撤销一步恢复原图。
 * “图表：”段落写标题，“图注：”段落写图注；返回是否已提交事务，找不到对应图片节点时返回 false。
 */
export function applyChartReplacement(
  view: EditorView,
  img: HTMLImageElement,
  imageSrc: string,
  text: ChartReplacementText,
): boolean {
  const located = locateImage(view, img)
  if (!located) return false
  const { from, node, blockEnd } = located
  const { title, altText } = text
  const tr = view.state.tr
  if (node.type.name === 'image-block') {
    tr.setNodeMarkup(from, undefined, { ...node.attrs, src: imageSrc, caption: altText ?? node.attrs.caption })
  } else {
    tr.setNodeMarkup(from, undefined, { ...node.attrs, src: imageSrc, alt: altText ?? node.attrs.alt })
  }
  const caption = findChartCaptionParagraph(view.state.doc, blockEnd)
  const captionText = caption?.prefix.startsWith('图表') ? title : altText
  if (caption && captionText !== null) {
    // 只替换段落内文本，保留段落节点本身。
    tr.insertText(`${caption.prefix}${captionText}`, caption.from + 1, caption.to - 1)
  }
  view.dispatch(tr)
  return true
}

export interface ChartAIEditHooks {
  /** 接受替换并写回正文后触发（自动保存由通用文档变更链路接管）。 */
  onReplaced?: (editId: string) => void
  onError?: (code: string) => void
}

export interface ChartAIEditController {
  open(img: HTMLImageElement): void
  dispose(): void
}

interface EditTarget {
  img: HTMLImageElement
  chartId: string
  imagePath: string
  title: string
  altText: string
  visualForm?: string | null
  previousEditId?: string
}

export function createChartAIEdit(options: {
  view: EditorView
  client: ReportEditorClient
  basePath: string
  /** 轮询间隔（毫秒）；生产 1500，测试可注入更小值。 */
  pollIntervalMs?: number
  hooks?: ChartAIEditHooks
}): ChartAIEditController {
  const { view, client, basePath, hooks } = options
  const pollIntervalMs = options.pollIntervalMs ?? 1500
  let modal: ReturnType<typeof createModal> | null = null
  let target: EditTarget | null = null
  let runningEditId: string | null = null
  let cancelled = false
  // 用户关闭了窗口：后台结果不再重新打开窗口抢焦点。
  let dismissed = false

  const ensureModal = () => {
    if (modal) return modal
    modal = createModal({
      root: document.body,
      overlayClass: 'chart-ai-edit',
      cardClass: 'chart-ai-edit-card',
      closeClass: 'chart-ai-edit-close',
      closeLabel: '关闭 AI 改图',
      labelledBy: 'chart-ai-title',
      variant: 'wide',
      content: `
        <div class="panel-header">
          <h2 id="chart-ai-title">AI 改图</h2>
          <p class="chart-ai-subtitle" data-role="subtitle">用自然语言调整这张图，改后先对比再替换</p>
        </div>
        <div class="chart-ai-body" data-role="body"></div>
      `,
      onRequestClose: () => {
        cancelled = true
        dismissed = true
        if (runningEditId && target) {
          void client.cancelChartAiEdit(target.chartId, runningEditId).catch(() => undefined)
        }
        modal?.close()
      },
    })
    return modal
  }

  const bodyOf = () => {
    const body = ensureModal().card.querySelector<HTMLElement>('[data-role="body"]')
    if (!body) throw new Error('chart ai panel body missing')
    return body
  }

  function baseTitleOf(img: HTMLImageElement): string {
    const block = img.closest('.milkdown-image-block')
    const caption = block?.nextElementSibling
    if (caption?.matches('p')) {
      const text = caption.textContent?.trim() ?? ''
      if (/^图表\s*[:：]/.test(text)) return text.replace(/^图表\s*[:：]\s*/, '')
    }
    return img.getAttribute('title') ?? img.alt ?? ''
  }

  async function resolveTarget(img: HTMLImageElement): Promise<EditTarget | { error: string }> {
    const src = img.getAttribute('src') ?? ''
    const altText = img.alt || baseTitleOf(img)
    try {
      // 已接受过的改图：按登记找回所属图表，以该改图为底图继续调整。
      const editId = chartEditIdFromSrc(src, basePath)
      const record = editId ? await client.chartEditRecord(editId) : null
      const charts = record ? [] : (await client.charts()).charts ?? []
      const matched = record ? null : matchChartForImage(charts, src, basePath)
      const chart = record
        ? { chartId: record.chartId, imagePath: record.imagePath }
        : matched
          ? { chartId: matched.chartId, imagePath: matched.imagePath }
          : null
      if (!chart) return { error: '这张图不在当前版本的登记图表中，无法改图。' }
      const availability = await client.chartAiAvailability(chart.chartId)
      if (!availability.available) {
        return { error: chartAiUnavailableReason(availability.reason) }
      }
      return {
        img,
        chartId: chart.chartId,
        imagePath: chart.imagePath,
        title: baseTitleOf(img),
        altText,
        visualForm: matched?.visualForm ?? null,
        ...(record ? { previousEditId: record.editId } : {}),
      }
    } catch {
      return { error: '无法获取图表登记信息，请稍后重试。' }
    }
  }

  function renderInputPhase(current: EditTarget, note?: string) {
    target = current
    const body = bodyOf()
    body.innerHTML = `
      <div class="chart-ai-current">
        <img alt="当前图表" src="${assetUrl(basePath, current.imagePath)}">
        <div class="chart-ai-current-meta">
          <p class="chart-ai-chart-title"></p>
          <p class="chart-ai-chart-alt"></p>
        </div>
      </div>
      ${note ? `<p class="chart-ai-note" role="status"></p>` : ''}
      <label class="chart-ai-label" for="chart-ai-instruction">改图要求</label>
      <textarea id="chart-ai-instruction" rows="3" maxlength="2000"
        placeholder="例如：改成横向柱状图并按金额降序，显示数值标签"></textarea>
      <div class="chart-ai-quick" role="group" aria-label="快捷指令"></div>
      <div class="chart-ai-actions">
        <button type="button" class="${buttonClasses('primary')}" data-action="submit">生成改图</button>
        <span class="chart-ai-hint">作图数据不变；超出已登记数据的要求会说明原因后跳过。</span>
      </div>
    `
    body.querySelector<HTMLElement>('.chart-ai-chart-title')!.textContent = `标题：${current.title || '（无）'}`
    body.querySelector<HTMLElement>('.chart-ai-chart-alt')!.textContent = `图注：${current.altText || '（无）'}`
    if (note) body.querySelector<HTMLElement>('.chart-ai-note')!.textContent = note
    const textarea = body.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    const quick = body.querySelector<HTMLElement>('.chart-ai-quick')!
    for (const command of quickCommandsForForm(current.visualForm)) {
      const chip = document.createElement('button')
      chip.type = 'button'
      chip.className = 'chart-ai-chip'
      chip.textContent = command
      chip.addEventListener('click', () => {
        const merged = textarea.value.trim() ? `${textarea.value.trim()}；${command}` : command
        textarea.value = merged.slice(0, MAX_INSTRUCTION_CHARS)
        textarea.focus()
      })
      quick.append(chip)
    }
    const submit = body.querySelector<HTMLButtonElement>('[data-action="submit"]')!
    const chartTemplates = (client as ReportEditorClient & {
      chartTemplates?: (chartId: string) => Promise<{ templates: { templateId: string; name: string; available: boolean; reason?: string }[] }>
    }).chartTemplates
    if (typeof chartTemplates === 'function') {
      void chartTemplates.call(client, current.chartId).then((catalog) => {
        const templates = document.createElement('div')
        templates.className = 'chart-ai-templates'
        templates.setAttribute('role', 'group')
        templates.setAttribute('aria-label', '预制图模板')
        for (const item of catalog.templates) {
          const control = document.createElement('button')
          control.type = 'button'
          control.className = 'chart-ai-chip chart-ai-template'
          control.textContent = item.name
          control.disabled = !item.available
          control.title = item.reason ?? ''
          control.addEventListener('click', () => void runTemplate(current, item.templateId, textarea.value.trim()))
          templates.append(control)
        }
        submit.parentElement?.before(templates)
      }).catch(() => undefined)
    }
    submit.addEventListener('click', () => {
      const instruction = textarea.value.trim()
      if (!instruction) {
        textarea.focus()
        return
      }
      void runEdit(current, instruction)
    })
    if (!dismissed) ensureModal().open(textarea)
  }

  async function runTemplate(current: EditTarget, templateId: string, instruction: string) {
    const body = bodyOf()
    cancelled = false
    body.innerHTML = '<p role="status">正在套用预制图模板…</p>'
    try {
      const started = await client.startChartTemplateEdit(current.chartId, {
        templateId,
        ...(instruction ? { instruction } : {}),
        ...(current.imagePath ? { baseImagePath: current.imagePath } : {}),
        ...(current.title ? { baseTitle: current.title } : {}),
        ...(current.altText ? { baseAltText: current.altText } : {}),
        ...(current.previousEditId ? { previousEditId: current.previousEditId } : {}),
      })
      runningEditId = started.editId
      for (;;) {
        await new Promise(resolve => setTimeout(resolve, pollIntervalMs))
        if (cancelled) return
        const state = await client.chartAiEditStatus(current.chartId, runningEditId)
        if (state.status === 'succeeded') {
          renderReviewPhase(current, state as unknown as ChartAIEditSuccess, `套用模板：${templateId}`)
          return
        }
        if (state.status === 'failed' || state.status === 'cancelled') {
          renderInputPhase(current, state.error?.message ?? '模板未完成，原图保持不变。')
          return
        }
      }
    } catch {
      renderInputPhase(current, '模板请求失败，原图保持不变。')
    } finally {
      runningEditId = null
    }
  }

  async function runEdit(current: EditTarget, instruction: string) {
    const body = bodyOf()
    cancelled = false
    body.innerHTML = `
      <div class="chart-ai-progress" role="status" aria-live="polite">
        <div class="chart-ai-current"><img alt="当前图表" src="${assetUrl(basePath, current.imagePath)}"></div>
        <p class="chart-ai-stage" data-role="stage">${STAGE_LABELS.queued}</p>
        <p class="chart-ai-hint">改图在后台执行，可关闭窗口稍后在同一张图上重新发起。</p>
        <div class="chart-ai-actions">
          <button type="button" class="${buttonClasses('danger')}" data-action="cancel">取消改图</button>
        </div>
      </div>
    `
    const stage = body.querySelector<HTMLElement>('[data-role="stage"]')!
    const cancel = body.querySelector<HTMLButtonElement>('[data-action="cancel"]')!
    cancel.addEventListener('click', () => {
      cancelled = true
      if (runningEditId && current.chartId) {
        void client.cancelChartAiEdit(current.chartId, runningEditId).catch(() => undefined)
      }
    })
    const started = performance.now()
    try {
      const startedResponse = await client.startChartAiEdit(current.chartId, {
        instruction,
        ...(current.imagePath ? { baseImagePath: current.imagePath } : {}),
        ...(current.title ? { baseTitle: current.title } : {}),
        ...(current.altText ? { baseAltText: current.altText } : {}),
        ...(current.previousEditId ? { previousEditId: current.previousEditId } : {}),
      })
      runningEditId = startedResponse.editId
      if (cancelled) {
        // 服务端返回编号前已取消：补发取消请求，避免后台任务继续占用该图与额度。
        void client.cancelChartAiEdit(current.chartId, runningEditId).catch(() => undefined)
      }
      let transientFailures = 0
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, pollIntervalMs))
        if (cancelled) break
        let state: Awaited<ReturnType<typeof client.chartAiEditStatus>>
        try {
          state = await client.chartAiEditStatus(current.chartId, runningEditId)
          transientFailures = 0
        } catch (error) {
          if (error instanceof TypeError && ++transientFailures < 5) continue
          throw error
        }
        const stageLabel = STAGE_LABELS[String(state.stage ?? 'queued')] ?? STAGE_LABELS.queued
        stage.textContent = `${stageLabel}（${Math.round((performance.now() - started) / 1000)} 秒）`
        if (dismissed) return
        if (state.status === 'succeeded') {
          renderReviewPhase(current, state as unknown as ChartAIEditSuccess, instruction)
          return
        }
        if (state.status === 'failed' || state.status === 'cancelled') {
          const error = (state as { error?: { code?: string; message?: string; skipped?: { request: string; reason: string }[] } }).error
          hooks?.onError?.(error?.code ?? 'report_editor_chart_ai_failed')
          const skippedNote = (error?.skipped ?? []).map(item => item.reason).join('；')
          renderInputPhase(
            current,
            error?.message
              ? `${error.message}${skippedNote ? `（${skippedNote}）` : ''}`
              : '改图未完成，原图保持不变，可调整要求后重试。',
          )
          return
        }
      }
      if (cancelled && !dismissed) {
        renderInputPhase(current, '已取消本次改图，原图保持不变。')
      }
    } catch (error) {
      hooks?.onError?.(error instanceof Error ? error.message : 'report_editor_chart_ai_failed')
      if (!dismissed) renderInputPhase(current, '改图请求失败，请稍后重试；原图保持不变。')
    } finally {
      runningEditId = null
    }
  }

  function renderReviewPhase(current: EditTarget, result: ChartAIEditSuccess, instruction: string) {
    const body = bodyOf()
    const changes: string[] = []
    if (result.changes.title) changes.push(`标题改为「${result.changes.title}」`)
    if (result.changes.altText) changes.push(`图注改为「${result.changes.altText}」`)
    if (result.changes.visualForm) changes.push(`图形改为「${result.changes.visualForm}」`)
    if (result.changes.plotDataUnchanged) {
      changes.push('作图数据未变（数值与原图一致）')
    } else {
      const added = result.changes.dataBindingsAdded ?? []
      changes.push(
        added.length
          ? `作图数据换绑：${added.map(item => `${item.dataPath}（${item.fields.join('、')}）`).join('；')}`
          : '作图数据有变化',
      )
    }
    body.innerHTML = `
      <div class="chart-ai-compare" role="group" aria-label="改图前后对比">
        <figure class="chart-ai-compare-item">
          <figcaption>原图</figcaption>
          <img alt="改图前的原图" src="${assetUrl(basePath, current.imagePath)}">
        </figure>
        <figure class="chart-ai-compare-item">
          <figcaption>新图（AI 改图结果）</figcaption>
          <img alt="AI 改图生成的新图" src="${assetUrl(basePath, result.imagePath)}">
        </figure>
      </div>
      <ul class="chart-ai-changes" aria-label="变更清单"></ul>
      ${result.warnings.length ? '<ul class="chart-ai-warnings" role="alert" aria-label="软告警"></ul>' : ''}
      ${result.skipped.length ? '<ul class="chart-ai-skipped" aria-label="未执行的要求"></ul>' : ''}
      <div class="chart-ai-actions">
        <button type="button" class="${buttonClasses('primary')}" data-action="accept">接受替换</button>
        <button type="button" class="${buttonClasses('secondary')}" data-action="continue">继续调整</button>
        <button type="button" class="${buttonClasses('quiet')}" data-action="discard">放弃</button>
      </div>
      <p class="chart-ai-hint">接受后正文图片与图注一并替换，可用撤销（⌘/Ctrl+Z）恢复原图；导出新版本后改图与原图一样可追溯。</p>
    `
    const changeList = body.querySelector<HTMLElement>('.chart-ai-changes')!
    for (const change of changes) {
      const item = document.createElement('li')
      item.textContent = change
      changeList.append(item)
    }
    const warnings = body.querySelector<HTMLElement>('.chart-ai-warnings')
    if (warnings) for (const warning of result.warnings) {
      const item = document.createElement('li')
      item.textContent = warning
      warnings.append(item)
    }
    const skipped = body.querySelector<HTMLElement>('.chart-ai-skipped')
    if (skipped) for (const item of result.skipped) {
      const entry = document.createElement('li')
      entry.textContent = `「${item.request}」未执行：${item.reason}`
      skipped.append(entry)
    }
    body.querySelector<HTMLButtonElement>('[data-action="accept"]')!.addEventListener('click', () => {
      const replaced = applyChartReplacement(view, current.img, result.imageSrc, {
        title: result.changes.title ?? null,
        altText: result.changes.altText ?? null,
      })
      if (!replaced) {
        hooks?.onError?.('report_editor_chart_ai_target_missing')
        renderInputPhase(current, '未能在正文中定位这张图（页面可能已变化），请重新打开后重试。')
        return
      }
      hooks?.onReplaced?.(result.editId)
      modal?.close()
    })
    body.querySelector<HTMLButtonElement>('[data-action="discard"]')!.addEventListener('click', () => {
      modal?.close()
    })
    body.querySelector<HTMLButtonElement>('[data-action="continue"]')!.addEventListener('click', () => {
      renderInputPhase(
        {
          ...current,
          imagePath: result.imagePath,
          previousEditId: result.editId,
          title: result.changes.title ?? current.title,
          altText: result.changes.altText ?? current.altText,
          visualForm: result.changes.visualForm ?? current.visualForm,
        },
        `已基于上一轮结果（${instruction.slice(0, 40)}${instruction.length > 40 ? '…' : ''}）继续调整。`,
      )
    })
  }

  return {
    open(img: HTMLImageElement) {
      dismissed = false
      const body = bodyOf()
      body.innerHTML = `
        <div class="chart-ai-progress" role="status" aria-live="polite">
          <p>${STAGE_LABELS.queued}</p>
        </div>
      `
      ensureModal().open()
      void resolveTarget(img).then((resolved) => {
        if (dismissed) return
        if ('error' in resolved) {
          body.innerHTML = `
            <div class="chart-ai-unavailable" role="alert">
              <p></p>
              <div class="chart-ai-actions">
                <button type="button" class="${buttonClasses('quiet')}" data-action="close">关闭</button>
              </div>
            </div>
          `
          body.querySelector('p')!.textContent = resolved.error
          body.querySelector('[data-action="close"]')!.addEventListener('click', () => modal?.close())
          hooks?.onError?.('report_editor_chart_ai_unavailable')
          return
        }
        renderInputPhase(resolved)
      })
    },
    dispose() {
      modal?.remove()
      modal = null
    },
  }
}
