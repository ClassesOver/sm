# 完整图片编辑、外部链接与测量标定（2026-11-13）

本轮继续原四格式完整功能组件、中文图标/桌面交互、原生文件持久化与Agno AI总目标，未把范围改成容易通过的少量按钮。上轮正式验收与盘点索引见NATIVE_COMPONENT_INVENTORY_20261113.md；本轮证据单列，未覆盖上轮。

持久根：/home/junge/codex-evidence/smart_reporting/office-image-links-measure-20261113。固定GenOffice源ref f8c17004fb730df11f0f743164ffd8b4281bb38c。

| 格式 | 组件完整范围 | 当前已证明 / 尚待证明 |
|---|---|---|
| Word | PictureDialogs Crop八手柄/移动、Cutout容差/透明预览/原分辨率PNG，以及ribbon替换 | final-v3以限定续验闭合14功能检查，161资源身份匹配；包含未保存genImage真实插入/裁切/撤销。实际DOCX 38527字节，正文/表格/第二图保持。原整轮与续段runner失败保留，不标整轮PASS。 |
| PPTX | CutoutDialog阈值/预览棋盘/去除百分比/原分辨率Apply/Cancel | final-v3唯一正式浏览器exit0，152资源、1save1download及新上下文重开；透明alpha/裁切/旋转/共享原图和其他parts独立回读通过。报告生成模块并发import漂移单列，不冒称整个Python环境冻结。 |
| XLSX | ExternalLinksPanel源/状态/工作表表格、Update/Locate/Change Source/Break确认 | 正式r1真实控件/计算/重载/撤销通过，save422失败；修复Python delivery白名单后，独立真实桥接RED→GREEN。等价重建草稿专项保存200/下载/修订5重开及ZIP回读通过；不是恢复原payload。4条资源请求失败保留。 |
| PDF | MeasureScaleDialog长度/单位/错误/取消确认、参考线实际校准 | final-v3唯一正式浏览器exit0，68资源身份匹配、0errors；两种UserUnit五条线、三窗口实际命中、UndoRedo/保存下载/修订5及独立AP标签通过。早期304误判原失败保留。 |

## 专家额外检查已落地

- 逐源核实控件和真正行为：PPTX源注释里的画笔仍是TODO，并没有可迁移实现；本轮完整阈值族不冒称画笔已完成。
- 核对编辑语义：源去背景应保留图片裁切、框、旋转及效果；已有默认换图清裁切不适用，新增可选keepSrcRect沿原native writer传递，常规换图默认行为保持。
- 实际导出媒体回读，而非仅看画布或schema；透明像素RGB允许编码器归零，须比较alpha和实际可见像素。ZIP目录entries不当作新增业务part。失败证据不删除或改写为原始PASS。
- 外链不自动访问URL或OS路径：只读用户明确选择的授权文件bytes，绑定来源摘要/尺寸/MIME/草稿；Update使用已有Univer公式引擎，未算公式必须明确skipped，不能伪报缓存更新。
- 测量按PDF物理points和UserUnit校准；比例只会话有效，每条Line独立保存标签，重新打开不凭旧会话猜比例；非ASCII单位受既有Helvetica writer限制时返回明确错误。
- PDF盘点从85文件增加334个词法控件与301个回调名称锚点，详见pdf/pdf-control-inventory.json；动态生成和条件组合仍需人工核对，文件/控件数均不是完成率。

## 验收边界

统一冻结final-source-v3源码清单5f915fbb9fd59ea46d19b980a43ccf120d7c42e199b46696a67665a227ad6e1d；Vite manifest 5658c601dbbba3447288e85c0da97914e99778719232d14c6ff1ce1f1bf01aa4，725静态文件清单0ecca13bbbc664cdbdd81a49658c48f0b8c9c20421d92ed7528eb57a4a1b8a74。tsc v2通过，v3仅vite分块与Python文件差异且兼容核对；Vite45.54秒与未提高的原预算通过。XLSX主包256.6KiB超额后，外链组件单独分块，降至248.6KiB。四引擎源码输入均匹配明确冻结runtime。

XLSX真实422根因是delivery/xlsx.py遗漏四种操作白名单，新增实际Python→CLI回归后修复。该单文件及测试单列python-final-v4身份，前端static与runtime仍v3/v1，不重建也不混称全v4。完整r1未通过；等价重建续验不冒充r1草稿恢复。对应286个成功资源身份匹配，但4条ECONNRESET/console失败保留，不能报告零请求错误。

业务validation=false时均保留具体原因与实际下载链接，未冒称业务验收通过。工作区外部并发变化继续保留；共享static/dist未替换，无提交、推送或部署。远端fetch遇GnuTLS -110、另次查询超时，当前HEAD与本地origin/code同为1138887，但不能据此保证远端最新。四格式完整穷举总目标仍未完成，证书/数字签名等unknown/partial不得改成完成。

单项验收：[Word图片](NATIVE_WORD_PICTURE_SOURCE_ACCEPTANCE_20261113.md)、[PPTX去背景](NATIVE_PPTX_CUTOUT_SOURCE_ACCEPTANCE_20261113.md)、[XLSX外部链接](NATIVE_XLSX_EXTERNAL_LINKS_SOURCE_ACCEPTANCE_20261113.md)、[PDF测量](NATIVE_PDF_MEASURE_SOURCE_ACCEPTANCE_20261113.md)。持久根root-batch-status.json汇总实际状态与失败边界。
