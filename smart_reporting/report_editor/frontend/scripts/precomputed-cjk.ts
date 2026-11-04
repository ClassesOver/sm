import * as cjk from 'cjk-regex'

// 固定版本的渲染器仅调用这三个方法的 toRegExp()。
// 保留公开 API 的精确结果，避免浏览器加载全部 Unicode 分类数据。
export function precomputedCjkModule(): string {
  return (['all', 'letters', 'punctuations'] as const).map(name =>
    `export function ${name}(){return {toRegExp:()=>new RegExp(${JSON.stringify(cjk[name]().toRegExp().source)})};}`,
  ).join('\n')
}
