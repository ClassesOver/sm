# PDF 测量标签、整组必填与表格槽宽验收（2026-11-11）

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批三域限定增量已完成验证；整体 PDF 对齐、完整转换保真和生产上线验收仍未完成。OCR 不在范围内，未提交、部署或启用生产开关。

## 本批改动与边界

文字：测量标签 Rect/AP BBox 改用正式 Helvetica 全字体保守 FontBBox、逐 glyph 无 kerning advance 和实际两位舍入 Tm，消除原估算外观框裁切。原 AP 命令、线条、9pt 字体和中点起写位置保持。单独绘图与样式改字混合路径共用实现。公开入口仍限可打印 ASCII；helper 拒绝与固定 writer literal 低字节不一致的编码，不扩大 Unicode 支持。标签与草稿居中位置差异、页边 CropBox 裁切、caret 与 Web 标记视觉差异继续开放，预览保留具体软告警。详见 NATIVE_PDF_MEASURE_LABEL_BOUNDS_ACCEPTANCE.md。

表单：复用 editFormWidget.required 为安全完整 2–64 Widget 互斥单选组切换“整组必填”。只改变目标字段 Ff 的 required 位，严格 xor2；保留所有原对象、值、默认值、状态、AP、Kids/Opt 和原引用，不引入默认字体对象。拒绝继承/间接/异常 flags、共享或不闭合 AP、混改和 no-op；不扩旧通用权限。UI、Undo/Redo、恢复草稿及后续填写 No 均有证据。任意复杂多 Widget、XFA、签名等仍未开放。详见 NATIVE_PDF_FORM_RADIO_REQUIRED_ACCEPTANCE.md。

转换：仅调整 emitTable 的宽度 claim 循环，将每个 grid column 按真实左右区间分摊到其覆盖的 slots，逐槽取已有更宽 claim；避免首槽整列宽再叠内部默认宽。保留 continuation override、重叠 max、未覆盖 gap、极窄聚类 fallback、内容及合并。最小 2 chars、固定 7px builder convention、宿主默认字体/MDW、正文二维排布与图片参考区均未解决。详见 NATIVE_PDF_XLSX_TABLE_SLOT_WIDTH_ACCEPTANCE.md。

## 冻结构建与身份核验

一次成功 Vite、一次 bridge bundle、一次 runtime package。376 个 JS 分块预算零超限；PDF main 249380 bytes，form controls 34295 bytes。static 为 `/tmp/pdf-label-required-slots-static`，manifest SHA-256 `91827fa9edeba6b0e70a0cc28660788b7577aded90c25943214aa3e87cd018d5`。runtime 为 `/tmp/pdf-label-required-slots-runtime`，CLI SHA-256 `f249a0b64f2db5d2c193f7ea983a2c6c21c5077bdd10d2221624465e7f4c993e`。

45 个前端文件、189 个引擎/清单文件、955 个实际 bundle inputs 最终核验匹配；LOCAL 184 项、converter 48 项本地 hash 与 69 个固定 Git blob 逐项匹配。三转换引擎许可/来源说明、converter 通告、两个 WASM 均匹配。已安装的 @pdf-lib/standard-fonts 1.0.0 从传递依赖显式登记为直接依赖，未升级实际包，运行包携带许可。

最终发现 SOURCE-SHA256.json 中 save-pdf.ts 的 localSha256 仍为之前字体适配版本 `5193cdcb…`，本批已改为实际 `ef072171…` 并补充测量适配说明；上游 sha256 不变。仅同步此元数据到 runtime，没有重做构建/打包。更正前 engine freeze 保留为 `/tmp/pdf-label-required-slots-engine-freeze-before-metadata.json`，更正记录为 `/tmp/pdf-label-required-slots-source-metadata-correction.json`；CLI 前后 SHA 完全相同。最终 freeze 只更新该清单一项，不把更正说成运行代码漂移。

## 实际浏览器与下载

三条真实链路均通过，各 37 个实际 JS 响应与同一冻结资源匹配，三域集合及 SHA 相同。来源未变，asset/page/console/HTTP errors 均空。真实 grant、cookie、CSRF、预览确认、签发下载及重开；文档/grant/产物仓储仍是内存 fixture，不冒称生产持久化或生产权限验收。

文字最终目录 `/tmp/pdf-label-required-slots-text-browser-retry`。实际 mixed.pdf 为 14434 bytes，SHA-256 `03a68461c5527839bb0b91c42d1599b4ad0886b88e937af1a0d6b688026d098a`。pointer 标定、改字/样式、underline、caret、第二短水平测量、Undo/Redo、预览确认和下载重开通过。独立 pypdf 固定核对 3.00 m / 0.04 m 及水平端点，Poppler 600×800 实际渲染与只扩大 Rect/BBox 的诊断副本差 0 像素；root 已目视实际 PNG。另有 native 水平短线 24W 等六类独立渲染，单独/混合各 1800×1400 差 0 像素。

首次文字 browser 已保存下载，但 verifier 仍硬编码旧斜线的 1.50 m，故最后一步失败。保留 `/tmp/pdf-label-required-slots-text-browser/failure.json`；只修 verifier 后，同一产物复读通过，默认旧 variant 仍拒绝新几何。由于失败进程未持久化实际 JS 资产集合及完整 summary，仅重试这一条失败 browser，另两域和已过 HTTP 不重跑；没有伪造恢复 summary。此失败是验收脚本旧预期，不冒称生产 RED。

表单目录 `/tmp/pdf-label-required-slots-form-browser`，5 次保存（radio、code、必填开、关、填 No）。required PDF 7647 bytes，SHA `992c4ad0a7db10c0cf881af16ef1900046e032d75191d77b12d72ebe58fd38e0`；optional 7647 bytes，SHA `9aaef9074e9531ec160f523f96cc092245feabd0330eb7c78f7d7caeef3f32e4`；后填 No 7766 bytes，SHA `56a978a72bff0acda1bbb8007b1edb4f5e63f3d8de911ba4652092eb8cab5463`。独立 pypdf 核全原始对象与流，required/optional 只变 Ff required 位，其他原引用/值/AP 保持；后填按既有语义改变 V/AS。root 已目视最终重开选中 No。

XLSX 目录 `/tmp/pdf-label-required-slots-xlsx-browser`，实际 converted.xlsx 5924 bytes，SHA `ee7576b9fae8b895c071178c93c66802279e125d310f441e85c1a312bc7cdf8b`。与上一批实际下载使用相同 source SHA `db01c13b8865a262ae9ce0123a38201b0071782e815f5091d401b9b455c3f373`。剥 cols 后逐 sheet XML、styles.xml 和 media bytes 不变。

对本批实际下载仅执行一次 Calc，profile/output 均在 /dev/shm，exit0（有非 fatal javaldx 警告）。实际打印 PDF 87363 bytes，SHA `946d6e4946cff42a67251afc8138974ed42c105e937e9b6d0706cd9a4fcfe810`。host 独立量测表头上边框可见段总长 787.4350→629.1500 pt、首列 262.6300→219.7700 pt，实际 6→4 页；builder convention 676.5→545.25 不是 host 物理 pt。root 已目视全部 4 页：表格仍横向拆页，正文二维关系及图片参考区仍不同，不能宣称源 2 页已还原。混合字体、数字类型、小数/货币/百分数精度专项通过，overallFidelityPassed、printLayoutFidelityPassed、defaultFontMdwFidelityPassed 均保持 false。

## 专项与非阻断契约

- 文字新增 native 2 项、受影响混合正向 1 项与 strict scoped 类型检查通过，保留真实 RED→GREEN；没有宣称全项目类型检查通过。
- 表单新增 native 5 项、受影响旧 native 8 项、flags 边界 1 项通过；UI 新 2 项及旧 9 项共 11 项通过。host 恢复草稿新增 1 项通过（14 skipped）；首次 fixture 误继承 append payload 的 rect/exportValue，修 fixture 后仅重试该项，不算生产缺陷。
- 转换新增 5 项真实 RED，首次 GREEN 4 项通过；剩余 sparse-array 断言修正后只重跑该项通过。三域交叉只读复审无阻塞发现。
- HTTP 新 styledMeasureBounds、requiredRadioGroup 后置故障，加受影响旧 measure 软告警及签发静态守卫，共 4 项唯一检查通过：`/tmp/pdf-label-required-slots-http-green.log`。真实长标签框及全对象 Ff 例外在 HTTP 层再次核验。
- 所有新后置失败点均已登记 test_http_publication_lineage.py；无新增 Python 生产签发函数。浏览器保存 validation=false 仍保留身份一致的实际文件及下载链接，具体问题保留，不冒称完整验收通过。

总证据 `/tmp/pdf-label-required-slots-final-evidence-20261111.json`，原子写入并读回。未重复完整测试。剩余任意混合编辑、完整游标/跨对象重排、测量中点/UI 居中与页边、复杂表单/XFA/签名、Office/MD/HTML 完整保真、PPTX 首行约 +6.350708 pt 和完整生产镜像/权限/部署等缺口继续保留。
