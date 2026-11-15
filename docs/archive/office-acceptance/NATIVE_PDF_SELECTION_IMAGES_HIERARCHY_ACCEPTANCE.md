# PDF 选区样式、XLSX图片与层级表单验收

2026-11-11。固定GenOffice ref：f8c17004fb730df11f0f743164ffd8b4281bb38c。OCR排除。
本批限定范围通过，PDF全功能对齐、完整保真及生产部署验收仍未完成。

## 本批交付与边界

- 文字：UTF-16选区字体/字号/颜色/粗斜体、焦点与选区保持、输入后范围重定位；复用固定源styleRuns与实际字体advance。仍限水平来源，不代表完整caret、自动reflow或任意编辑混用。整对象改样式同步清除同字段选区覆盖的源交互未接。
- XLSX：正常页真实图像进入可编辑单元格之后的标注参考区；透明、对象/页旋转、CropBox原点与PNG像素裁剪经独立读回。参考区不是原位图文排版；超预算、跨界JPEG等逐图告警，保留已有输出。
- 表单：最多16段/总长256的ASCII层级名称、Parent/Kids闭合、父节点复用、前缀冲突；已有安全单选组追加未选中Widget，最多64控件，保留旧选择/required/控件/AP。旧删除门禁未放宽。
- 公共接线：严格参数、cap、草稿恢复、实际PDF确认和回执；styleRuns-only与appendRadioWidget的HTTP后置复核故障均保留真实下载，validation不假通过。

## 冻结构建与浏览器

静态目录：/dev/shm/pdf-next-static-20261111-root02。
运行包：/dev/shm/pdf-next-runtime-20261111。
PDF主包241257字节（235.6KiB），低于250KiB；精确拆分表单模块，未提高阈值。
LOCAL-SHA256.json的151项与转换SOURCE-SHA256.json的48项local哈希一致，原始sourceSha256未覆盖。
PDF_SMOKE_STATIC_DIRECTORY同时绑定router与StaticFiles，避免并行共享static重建影响；结论仅对应本快照。

manifest SHA256：4f618f6766d44112982ccf8fd18384db72fec7bd8ba2e245d14c5f169fa68e09。

CLI SHA256：d57204f18ee14eb55d9ac3d1b98a4e3cfa4b1e2dc941417072d64bdfaac2c270。

三域均使用Chromium140.0.7339.16、真实grant/cookie/CSRF与下载路由；仅夹具仓储在内存。每域36个JS资源SHA匹配快照，pageErrors/consoleErrors/httpErrors/assetErrors均为空，sourceUnchanged=true。

- text：/tmp/pdf-text-selection-browser-20261111-root01；summary与independent均ok=true。
- forms：/tmp/pdf-form-hierarchy-browser-20261111-root01；summary与independent均ok=true。
- xlsx：/tmp/pdf-xlsx-images-browser-20261111-root02；summary与independent均ok=true。

文字修订4→5，真实键盘选区/UndoRedo/preview/确认/12030字节PDF下载/重开；pypdf验证AA/BB/CC实际字体、字号、红色、基线与advance，另外两页保留。
表单修订4→9；两层级字段、原生radio组、追加及填写五次保存下载重开；逐份独立校验树/Annots/AP/原正文；只在append阶段声称旧AS/AP严格不变。
XLSX真实授权转换下载；openpyxl/ZIP/Pillow验证三页正文/数值、九图、透明RGBA/坐标/裁切/锚点，manualReview=true且validation=false。
汇总机器证据：/tmp/pdf-selection-images-hierarchy-final-evidence-20261111.json。临时目录不是生产持久存储。

## 定向验证

未重复完整测试。领域专项及相邻回归见各专属文档，root集成证据：

- 公共引擎分派2PASS：/tmp/pdf-selection-radio-integration-green-20261111.log。
- 表单宿主7PASS：/tmp/pdf-radio-host-green-20261111.log；预览确认6PASS：/tmp/pdf-radio-confirmation-20261111.log。
- styleRuns后置故障HTTP1PASS：/tmp/pdf-next-http-faults-20261111.log。该日志另有首轮radio夹具仅1选项不符合原min2约束的失败，不计通过。
- 修正合法双选项夹具后的radio后置故障HTTP1PASS：/tmp/pdf-next-radio-http-fault-20261111.log。
- 静态目录与签发守卫2PASS：/tmp/pdf-next-static-signing-20261111.log。
- 分块规则1PASS：/tmp/pdf-next-chunks-green-20261111.log；PDF scoped tsc无错误：/tmp/pdf-next-types-final-20261111.log。
- Vite成功：/tmp/pdf-next-vite-final-20261111.log；非PDF Word locale循环分块与大型chunk告警仍在，不属本批修复范围。

## 失败迭代与剩余范围

首个快照主包259.6KiB超预算，拆分后最终235.6KiB。XLSX browser root01转换成功，但harness误将结构化issue当字符串调用includes而失败；修正读取issue.message后root02完整通过，原失败证据保留。构建配置测试早期遇应用插件/URL测试环境问题，改为Node环境精确验证原规则，最终缺规则RED和实际规则GREEN均有记录。
文档收尾曾遇根分区ENOSPC导致状态文档写入中断；旧验收运行包逐文件SHA核对后迁到/dev/shm，原路径保留为symlink；状态按仓库基线、已记录状态及已有验收文档恢复，后续改为原子替换。实际验收文件完整保留。

完整游标/自动reflow/任意混合编辑、复杂PPTX/字体/原位图文完整保真、复杂多Widget/XFA/签名字段与真实证书签名仍未覆盖；证书服务仍为外部依赖。
保存业务验收仍可能native_source_review_pending，转换仍须人工验收；文件下载不等于内容通过。未运行完整应用镜像或生产DB/身份验收，未部署、提交或开启生产开关。

专属详情：NATIVE_PDF_TEXT_SELECTION_ACCEPTANCE.md、NATIVE_PDF_XLSX_IMAGES_ACCEPTANCE.md、NATIVE_PDF_FORM_DESIGN_ENGINE_ACCEPTANCE.md。
