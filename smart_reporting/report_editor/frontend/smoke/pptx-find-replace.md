# PPTX 原生查找替换

固定来源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/slides/src/renderer/components/FindReplaceDialog.tsx` 与 `replaceAllInDeck`。Web 适配保留默认不区分大小写、字面正则转义、非重叠匹配、元素级循环导航、当前对象首个替换和全部替换。替换值中的 `$&`、`$1` 作为普通文字。查找不创建草稿，全部替换由调用方一次写入完整 `NativeDraft` 快照，原子撤销。

本次范围仅为来源顶层文本框/形状中桥接层明确标记 `findReplaceEditable: true` 的单普通 run 段落。排除混合 run、动态域、链接、软换行、未知扩展、组合/表格/母版和新增对象；普通多段落可替换，但查找与替换值均不能跨段落。标准形状 creationId 扩展不影响文字，可原样保留。替换读取待保存 edits、页面顺序与删除状态，合并保留原几何和其他 edits。对话框提示范围，失败保留对话框及原因。此边界避免现有纯文字写回将混合格式折叠成单一格式。

定向验证：

```sh
cd smart_reporting/report_editor/frontend
npx vitest run src/slides-find-replace.test.ts
npx tsc --noEmit
cd ../../reporting/slides_engine
npx vitest run bridge/tests/pptx-find-replace.test.ts
```

`smoke/pptx-parallel-edit-smoke.mjs` 是独立静态构建浏览器验收。它使用明确的授权/CSRF route fixture，真实调用 Python inspect/patch/render，不能替代生产认证测试；辅助 PDF 预览 iframe 使用有效占位 PDF fixture，不测试真实 PDF 转换。浏览器真实上传图片、替换来源图片、改原生图表数据与类型、全部替换，验证撤销/重做、刷新恢复、保存新修订、实际下载 SHA/大小、独立 python-pptx/ZIP 回读和修订 2 重开。每个实际 JS 响应与磁盘冻结构建核对身份，结束复核 manifest 不变。运行前由主任务统一构建并冻结 dist：

```sh
PPTX_EXPECTED_MANIFEST_SHA256=<manifest-sha256> \
  PPTX_STATIC_ROOT=/tmp/frozen-static \
  node smoke/pptx-parallel-edit-smoke.mjs
```

默认产物：`/tmp/pptx-parallel-edit-smoke/{source.pptx,downloaded.pptx,evidence.json,before-save.png,revision-2.png}`。可用 `PPTX_SMOKE_EVIDENCE_DIR` 和 `PPTX_SMOKE_PORT` 设置输出位置和预览端口。并行任务可能重建共享产物时，使用 `PPTX_STATIC_ROOT` 指向已核验的独立静态目录快照；脚本会从该目录提供页面并逐个核对真实 JS 响应身份。未完成 checkpoint 明确标记 `completed: false`。
