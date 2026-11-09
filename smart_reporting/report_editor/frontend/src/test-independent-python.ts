import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

/** 独立回读（openpyxl 等）所用 Python：SR_INDEPENDENT_PYTHON 显式指定 > 仓库根
 *  .venv（与后端同一解释器）> PATH 上的 python3。不写死开发者本机绝对路径。 */
export const independentPython = (): string => {
  const configured = process.env.SR_INDEPENDENT_PYTHON
  if (configured) return configured
  const repoVenv = resolve(__dirname, '../../../../.venv/bin/python')
  return existsSync(repoVenv) ? repoVenv : 'python3'
}
