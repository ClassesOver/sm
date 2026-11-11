import type { UniverRuntime } from './workbook-vendor/grid/create-univer'
import { installCellFilenameFunction } from './workbook-function-cell'
import { installRateFallback } from './workbook-function-rate'
import { installIfsEmptySetFix } from './workbook-function-ifs'
import { installCriteriaCompareCacheFix } from './workbook-function-criteria'

/** 原生provider就绪后统一安装，所有权和迟到回调由各源适配器管理。 */
export function installWorkbookFunctionOverrides(runtime: Pick<UniverRuntime, 'univer'>, path: () => string | undefined) {
  const handles = [installCellFilenameFunction(runtime, path), installRateFallback(runtime), installIfsEmptySetFix(runtime), installCriteriaCompareCacheFix()]
  return { dispose() { handles.forEach(handle => handle.dispose()) } }
}
