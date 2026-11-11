/** 特殊缩进：twips正数首行、负数悬挂、零取消；可附带首行字符单位（百分之一字符）。 */
export function validDocxSpecialIndent(value: unknown, firstLineChars?: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && Math.abs(value) <= 14400
    && (firstLineChars === undefined || value >= 0 && typeof firstLineChars === 'number'
      && Number.isInteger(firstLineChars) && firstLineChars >= 1 && firstLineChars <= 10000)
}
