import { bindHfProbeParent } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-dom'

/** 隐藏HF测量与真实Word画布共享动态文档样式的祖先作用域。 */
export function createDocxHfProbeScope(host: HTMLElement) {
  return bindHfProbeParent(host)
}
