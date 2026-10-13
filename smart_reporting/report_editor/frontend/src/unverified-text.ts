/** 仅兼容没有 reviewNotices 的旧修订；新报告使用服务端登记的提示类型。 */
export function isExplanatoryUnverified(text: string, index: number): boolean {
  const prefix = text.slice(0, index)
  return /(?:原因|单位|口径|完整性|状态)\s*$/.test(prefix) ||
    /是否(?:涉及|存在)[^。！？；;，,\n]*$/.test(prefix)
}
