# 已有日期字段复制计划（2026-11-14）

目标：在已有来源字段复制链上补齐安全日期字段，保留实际 V/DV/DA/AP、内建 AFDate 格式及输入动作，支持同文档跨页。

方案：复用当前 copyFrom 深复制和原来源批次预检；仅允许既有 inspectDesignDateActions 精确识别的四种内建格式动作，不新建 JavaScript 解析器或放宽任意动作。前端复用只读副本卡片，模型不能传入/覆盖脚本或日期格式。

范围：单 Widget、未保护未签名安全 AcroForm；格式 yyyy-mm-dd、mm/dd/yyyy、dd/mm/yyyy、yyyy/mm/dd。保留原尺寸/同父命名；radio、签名、复杂日期脚本与任意多 Widget 仍受限。原 Widget 迁页尚未确认为固定源支持功能，不以现有限制证明缺口。

- [x] 引擎 RED：四格式跨页复制、动作图私有、后续填值保留及非标准脚本/未知属性拒绝。
- [x] 最小实现：form-copy-safety.ts 复用精确动作检查，form-design-create.ts 允许来源 date；不改发布/下载链。
- [x] 前端 RED/实现：日期来源 clipboard、恢复/模板校验、画布公共菜单与只读副本卡片。
- [x] 受影响定向测试、隔离 CLI、真实服务保存下载和浏览器实际复制/预览，独立 PDF 回读。
- [x] 记录失败/通过与既有全局类型诊断，更新有效缺口并独立静态复核；不重复完整套件。

结果见 NATIVE_PDF_SOURCE_DATE_COPY_ACCEPTANCE_20261114.md。
