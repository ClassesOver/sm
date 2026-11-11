import { createModal } from './modal'
import type { SparklineSpec } from '@sheets-web/xlsx-engine'

export type SparklineGroupEdit = { type?: 'line' | 'column' | 'stacked'; color?: string; negativeColor?: string; markers?: boolean; showAxis?: boolean }
export interface SparklineEditTarget { sheetId: string; target: string }

export function createSparklineDialog(root: HTMLElement, apply: (updates: SparklineGroupEdit, target: SparklineEditTarget) => void) {
  const modal = createModal({ root, label: '编辑迷你图', closeLabel: '关闭编辑迷你图', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog', content: `<h2>编辑迷你图</h2><form><label>类型<select aria-label="迷你图类型"><option value="line">折线</option><option value="column">柱形</option><option value="stacked">盈亏</option></select></label><label>系列颜色<input aria-label="系列颜色" type="color"></label><label>负值颜色<input aria-label="负值颜色" type="color"></label><label><input aria-label="显示标记" type="checkbox">显示标记</label><label><input aria-label="显示坐标轴" type="checkbox">显示坐标轴</label><p role="alert"></p><div><button type="button" data-sparkline-cancel>取消</button><button type="submit">确定</button></div></form>` })
  const type = modal.card.querySelector<HTMLSelectElement>('select')!, colors = modal.card.querySelectorAll<HTMLInputElement>('input[type=color]'), markers = modal.card.querySelector<HTMLInputElement>('[aria-label="显示标记"]')!, axis = modal.card.querySelector<HTMLInputElement>('[aria-label="显示坐标轴"]')!, error = modal.card.querySelector<HTMLElement>('[role=alert]')!
  let target: SparklineEditTarget | undefined
  modal.card.querySelector('[data-sparkline-cancel]')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => { event.preventDefault(); try { if (!target) throw new Error('请重新选择迷你图宿主'); apply({ type: type.value as SparklineGroupEdit['type'], color: colors[0]!.value, negativeColor: colors[1]!.value, markers: markers.checked, showAxis: axis.checked }, target); modal.close() } catch (cause) { error.textContent = (cause as Error).message } })
  return { open(spec: SparklineSpec, captured: SparklineEditTarget) { target = { ...captured }; type.value = spec.kind === 'winLoss' ? 'stacked' : spec.kind; colors[0]!.value = spec.color ?? '#376092'; colors[1]!.value = spec.negativeColor ?? '#D00000'; markers.checked = spec.markers === true; axis.checked = spec.showAxis === true; error.textContent = ''; modal.open(type) }, close: modal.close, dispose: modal.remove }
}
