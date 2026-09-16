import type { ToolbarMode } from './viewport'

export interface EditorShell {
  editor: HTMLElement
  outline: HTMLElement
  outlineToggle: HTMLButtonElement
  viewToggle: HTMLButtonElement
  search: HTMLButtonElement
  history: HTMLButtonElement
  templates: HTMLButtonElement
  more: HTMLButtonElement
  shortcuts: HTMLButtonElement
  focus: HTMLButtonElement
  focusExit: HTMLButtonElement
  exportSettings: HTMLButtonElement
  status: HTMLElement
  statusLabel: HTMLElement
  retry: HTMLButtonElement
  save: HTMLButtonElement
  exportPdf: HTMLButtonElement
  exportWord: HTMLButtonElement
}

export function createEditorShell(root: HTMLElement, mode: ToolbarMode): EditorShell {
  root.className = `report-app toolbar-${mode}`
  root.innerHTML = `
    <header class="app-bar">
      <div class="report-identity">
        <span class="product-mark" aria-hidden="true">R</span>
        <div>
          <h1>智能报告</h1>
          <p class="revision-label"></p>
        </div>
      </div>
      <div class="save-state" role="status" aria-live="polite" aria-busy="true">
        <span class="save-state-label">载入中</span>
        <button type="button" class="save-retry" hidden>重试</button>
      </div>
      <nav class="report-actions" aria-label="报告操作">
        <div class="toolbar-group toolbar-group-navigation"><button type="button" data-action="outline" aria-label="显示或隐藏目录"
          aria-controls="report-outline" aria-expanded="${mode === 'full'}" title="目录">
          <i data-lucide="panel-left" aria-hidden="true"></i>
          <span>目录</span>
        </button></div>
        <div id="report-secondary-actions" class="secondary-actions toolbar-group toolbar-group-edit-view" aria-label="编辑与视图">
          <button type="button" data-action="view" aria-label="切换页面宽度"
            aria-pressed="true" title="切换 A4/宽屏"><i data-lucide="maximize-2" aria-hidden="true"></i><span>A4</span></button>
          <button type="button" data-action="search" aria-label="搜索和替换" title="搜索和替换"><i data-lucide="search" aria-hidden="true"></i><span>搜索</span></button>
          <button type="button" data-action="history" aria-label="版本历史" title="版本历史"><i data-lucide="history" aria-hidden="true"></i><span>历史</span></button>
          <button type="button" data-action="templates" aria-label="报告模板" title="报告模板"><i data-lucide="layout-template" aria-hidden="true"></i><span>模板</span></button>
          <button type="button" data-action="shortcuts" aria-label="快捷键帮助" title="快捷键帮助"><i data-lucide="keyboard" aria-hidden="true"></i><span>快捷键</span></button>
          <button type="button" data-action="focus" aria-label="进入专注模式" aria-pressed="false" title="专注模式"><i data-lucide="focus" aria-hidden="true"></i><span>专注</span></button>
        </div>
        <button type="button" data-action="more" aria-label="更多操作"
          aria-controls="report-secondary-actions" aria-expanded="false" title="更多操作">
          <i data-lucide="more-horizontal" aria-hidden="true"></i>
          <span>更多</span>
        </button>
        <div class="toolbar-group toolbar-group-output"><button type="button" class="is-primary" data-action="save" aria-label="保存" title="保存">
          <i data-lucide="save" aria-hidden="true"></i><span>保存</span>
        </button>
        <button type="button" data-action="pdf" aria-label="导出 PDF" title="导出 PDF">
          <i data-lucide="file-down" aria-hidden="true"></i><span>PDF</span>
        </button>
        <button type="button" data-action="word" aria-label="导出 Word" title="导出 Word">
          <i data-lucide="file-text" aria-hidden="true"></i><span>Word</span>
        </button></div>
        <button type="button" class="is-subtle toolbar-settings" data-action="export-settings" aria-label="导出设置" title="导出设置"><i data-lucide="settings-2" aria-hidden="true"></i><span>设置</span></button>
      </nav>
      <span class="reading-progress" role="progressbar" aria-label="报告阅读进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"></span>
    </header>
    <div class="report-meta" aria-label="编辑状态说明">
      <span>内容格式：Markdown</span>
      <span class="meta-dot">·</span>
      <span>自动保存已开启</span>
      <span class="meta-dot">·</span>
      <span class="current-section">当前位置：报告开头</span>
      <span class="meta-spacer"></span>
      <span class="doc-metrics" aria-live="polite">0 字 · 0 段 · 阅读 0 分钟</span>
      <span class="meta-dot">·</span>
      <span class="structure-status">结构检查中</span>
      <span class="meta-dot">·</span>
      <span class="network-status">网络已连接</span>
      <span class="meta-dot">·</span>
      <span class="image-quality-status">图片检查中</span>
      <span class="meta-dot">·</span>
      <span class="focus-hint">专注模式：⌘/Ctrl + Shift + F</span>
      <span class="meta-dot">·</span>
      <span>可导出 PDF / Word</span>
    </div>
    <div class="report-workspace">
      <aside id="report-outline" class="report-outline${mode === 'compact' ? ' is-collapsed' : ''}"
        aria-label="报告目录">
        <div class="outline-heading"><span>目录</span></div>
        <nav class="outline-list" aria-label="章节导航"></nav>
      </aside>
      <section class="editor-surface" aria-label="报告正文">
        <div id="report-editor" aria-busy="true"></div>
      </section>
    </div>
    <button type="button" class="back-to-top" aria-label="回到报告顶部" title="回到顶部" hidden>↑</button>
    <button type="button" class="focus-mode-exit">退出专注</button>
  `
  const required = <T extends Element>(selector: string): T => {
    const element = root.querySelector<T>(selector)
    if (!element) throw new Error(`missing editor shell element: ${selector}`)
    return element
  }
  return {
    editor: required<HTMLElement>('#report-editor'),
    outline: required<HTMLElement>('.report-outline'),
    outlineToggle: required<HTMLButtonElement>('[data-action="outline"]'),
    viewToggle: required<HTMLButtonElement>('[data-action="view"]'),
    search: required<HTMLButtonElement>('[data-action="search"]'),
    history: required<HTMLButtonElement>('[data-action="history"]'),
    templates: required<HTMLButtonElement>('[data-action="templates"]'),
    more: required<HTMLButtonElement>('[data-action="more"]'),
    shortcuts: required<HTMLButtonElement>('[data-action="shortcuts"]'),
    focus: required<HTMLButtonElement>('[data-action="focus"]'),
    focusExit: required<HTMLButtonElement>('.focus-mode-exit'),
    exportSettings: required<HTMLButtonElement>('[data-action="export-settings"]'),
    status: required<HTMLElement>('[role="status"]'),
    statusLabel: required<HTMLElement>('.save-state-label'),
    retry: required<HTMLButtonElement>('.save-retry'),
    save: required<HTMLButtonElement>('[data-action="save"]'),
    exportPdf: required<HTMLButtonElement>('[data-action="pdf"]'),
    exportWord: required<HTMLButtonElement>('[data-action="word"]'),
  }
}
