# PDF 页面提取前端接线增量

2026-11-11。对固定 GenOffice `f8c17004` 的页面提取入口作 Web 适配：来源为已保存修订，服务端创建独立 PDF 文档，保留原文件与当前草稿。不是覆盖当前文档，也不把页面内 N 合 1 当成文件提取。

## 实现范围

- `pdf-page-ribbon.ts` 启用 `genoffice.pdf.page.extract`，`pdf-main.ts` 接入独立 `pdf-extract-dialog.ts`。
- 输入 1-based 页码或升序范围，多个片段按输入顺序组合；空值、重复、负数、小数、倒序范围和越界页码均拒绝。例 `4,1-2` 对应输出顺序 `[4,1,2]`。
- 仅在可编辑来源、无保存/预览/打印、无草稿操作或未暂存文字时启动；提交时再次检查，强制派发 click 不能绕过这些限制。
- `createNativeApi.extractPages` 沿用原生不可变 document/revision 路由、同源凭据、CSRF 和来源 SHA，调用 `/api/extract-pages`。
- 显示实际 PDF 下载及独立编辑入口，不自动跳转；`validation.ok=false` 显示“验收未通过”及具体原因，同时保留有效下载。拒绝跨源、非 HTTP(S) 链接。
- 关闭对话框不冒充撤销服务器操作；迟到结果不会写入已关闭/销毁的界面。关闭后的成功结果保存在该视图内存，重新打开可查看。相同页码重试沿用请求身份。
- 产品说明明确首批支持无表单、批注或保护信息的 PDF；书签和附件不保留。

## 定向验证

没有重复运行完整测试或完整构建。

1. `pdf-extract-dialog.test.ts` 与 `native-pdf-extract-api.test.ts` 首轮 RED：模块/方法不存在。实现后加上受影响 Ribbon 用例，8 项 GREEN。
2. `pdf-extract-entry.test.ts` 挂载真实 `createPdfEditorView`，仅 PDF.js 渲染边界使用替身；2 项 GREEN：实际 Ribbon 打开→请求→结果链接→来源草稿不脏，以及只读/保存/未保存草稿的强制触发拒绝。夹具初轮缺 viewBox 和按钮微任务等待已修，未修改产品守卫。
3. 类型检查首轮仅发现新测试中零参 mock 的类型推断，已修正；随后检查仅报并行新建 `pdf-form-design.test.ts` 尚缺实现文件，不把这一中间结果记为全局类型通过。最终统一构建由 root 另行记录。

## 新构建真实浏览器全链：通过

root 的最终 Vite 资产构建已完成，44.90 秒，日志 `/tmp/pdf-parallel-vite-build-20261111.log`。统一 `pnpm build` 的类型阶段被工作区 `workbook-print-header-footer.test.ts` 三处无关类型错误阻断，因此这里只记录单独 Vite 构建与实际运行通过，不记统一类型检查通过。

- 证据目录 `/tmp/pdf-extract-built-20261111-final-02`，`summary.json` 为 `ok=true`，Node session14983 exit0。Chromium `140.0.7339.16`，manifest SHA256 `6fbdb541ca7e617bff0f7a3cb6891ccb039699b6d63178a482cc11384e43c918`。
- 新增 `smoke/pdf-extract-server.py` 与 `smoke/pdf-extract-smoke.mjs`；真实 FastAPI/uvicorn → 原生签名 grant 兑换 → HttpOnly 会话 cookie → CSRF → `NativeEditorService` → 真实 PDF 引擎 → `NativePublicationService` → 下载 → 新编辑 grant 重开。仅文档、授权与持久产物仓储使用已有内存 fixture；不替换 API/handler/文件/引擎，也不需要模型 provider。
- 实际页面 Ribbon 打开“提取页面”，输入 `3,1`；只有一次 `/api/extract-pages` POST200。新文档独立 `documentId`、revision1、parentRevision=null、revisionRegistered=true，来源为 derived 并绑定父文档/修订/SHA。
- `validation.ok=false` 与 `native_validation_pending` 原因完整保留；实际界面显示“验收未通过”以及真实 PDF 下载和独立编辑链接。
- 实际下载1805字节，SHA256 `5ccaa1c5a975430fb6ef01c5f6009653c098e1984e3634f8b09516e9aeba0548`，与服务回执一致。独立 Python/pypdf 回读 `downloaded.pdf` 的正文依次为 `source page three`、`source page one`，见 `independent.json`。
- 新 grant 实际重开两页文档；真实 `/api/context` 为派生 child identity、origin=derived、sourceFile SHA 与下载一致，仍可编辑。源 PDF SHA256 `3a82cf75602914abcf6bf87be85c1d97586c225ac726bb16a16648c7c5c2d163` 与调用前一致，本地草稿存储不变，零 save/export 请求。
- 22个实际加载 JS response 的字节 SHA 逐个匹配冻结磁盘资产；结束时 manifest 仍相同。pageErrors/consoleErrors/httpErrors 全为空。
- 已逐张实际目视 `extracted.png` 和 `reopened.png`：中文范围说明、未通过原因、两链接显示清楚，重开后第1页为原第3页、第2页为原第1页。
- 失败历史 `/tmp/pdf-extract-built-20261111-final-01` 保留：沙箱内异步文件初始化停滞，60秒就绪超时；仅有 Matplotlib 默认 cache 只读警告，没有进入浏览器。沙箱外 final-02 才完成真实功能验收，不把第一轮计通过。

## 仍未验收范围

本次覆盖无表单/批注/保护的合成三页 PDF。复杂来源、多来源插入/替换/合并、生产 PostgreSQL 与完整部署身份/网络仍未由本增量证明；不能因此关闭完整 PDF 对齐或生产上线验收。
