# 已有日期字段复制验收（2026-11-14）

本批在安全来源字段复制上增加单控件日期字段，复用 copyFrom 原身份及现有深复制、草稿、预览确认和修订下载链。保留实际当前值、默认值、必填、DA/AP、字体及内建格式/输入动作；同文档跨页可用，原字段不变。

## 范围

仅允许现有 inspectDesignDateActions 精确验证的四格式：yyyy-mm-dd、mm/dd/yyyy、dd/mm/yyyy、yyyy/mm/dd。字段必须是安全单 Widget 文本字段；字段/Widget 双方动作须同格式。许可绑定实际 PDFDict，不从字符串模式猜测脚本；额外脚本、未知键、非标准格式、非文本字段借用日期动作及格式不匹配均不获得复制能力。客户端不得提供脚本或覆盖 dateFormat/value 等属性。

辅助动作图随字段私有深复制；副本保持尺寸与同父命名，未保存时仅移动/删除/复制。复杂日期脚本、radio/签名及任意多 Widget 仍受限；系统/跨文档剪贴板未实现。Web 浏览器未执行 Acrobat 日期脚本，本验收证明 PDF 中的动作保留，不冒称浏览器日期格式校验等价。

## 定向证据

- 引擎初始 RED：`/tmp/pdf-source-date-engine-red.log`，已有日期字段未获 copyEditable；零写和恶意脚本拒绝项当时通过。
- 引擎关联 GREEN：`/tmp/pdf-source-date-engine-final.log`，16 项通过（新日期 3 项及原来源复制/创建/设计安全）。四格式覆盖间接 AA/F/K 私有对象、不同 V/DV、跨页/AP/正文/原字段、后续填值保留与全批原来源零写。
- 新增非文本/格式不匹配专测：`/tmp/pdf-source-date-nontext.log`，仅新增 1 项通过，没有重跑已通过全集。
- 前端初始 RED：`/tmp/pdf-source-date-front-red.log`，clipboard 和实际画布菜单 2 项失败；最终 `/tmp/pdf-source-date-front-final.log` 为 53 项通过（clipboard 10、画布 34、创建 7、批创建 2）。
- 真实服务：`/tmp/pdf-source-date-service.log` 为 1 项通过、1 项未选；只运行新增 date 参数，未重复 text 参数。实际 preview/preview_file、未确认保存拒绝、确认保存、修订登记、HTTP 下载流及 pypdf 核验均通过；validation.ok=false 保留真实下载，来源不变。保留 imghdr 弃用提示。
- 真实浏览器：`/tmp/pdf-source-date-browser/evidence.json` 为 ok:true。真实固定 FormDesignLayer/PDF.js/隔离 CLI，完成日期快捷键复制/重复、菜单跨页粘贴、Undo/Redo、刷新恢复和实际 PDF 预览。输出三个日期字段，页面 Widget `[2,1]`，动作 dd/mm/yyyy、当前值 14/11/2026、默认值 02/01/2025、必填/AP 均保留，来源不变，页面/HTTP 错误为空。浏览器适配不含生产授权/发布，服务验证由上述 Python 测试承担。
- `/tmp/pdf-source-date-browser/font-readback.json` 为对同一实际 PDF 的独立追加回读：原字段和两副本的 AP 均为 Times-BoldItalic；未重新生成或重跑完整浏览器。
- 窄屏和实际预览截图已目视，390px 卡片 left62/right382，clientWidth=scrollWidth318，无卡片横向溢出；正文沿用宿主横向阅读，副本允许重叠。
- 全局类型 `/tmp/pdf-source-date-types.log` 与前一批基线逐字节相同，仍为既有 632 条诊断，不能称全项目通过。
- 独立同模型 reviewer 静态复核无重要问题；不将静态复核称作测试。

隔离 CLI 位于 `/tmp/pdf-source-date-runtime/dist/cli.mjs`，SHA256 `c278bf9774fc247f4b21460ceb16fe533986d18e5db46abb24e7e70ab36a2deb`，6,160,551 字节。没有修改共享 static/dist、提交、推送或部署。Vite 保留 sibling 项目 fast-xml-parser/saxes/utif2 依赖预扫描告警，实际 PDF 页面正常。

## 中文界面续验

初轮烟测 HTML 未声明 lang，工具栏按现有规则回退英文；正式 native.html 仍为 zh-CN，并非正式入口改为英文。用户指出后补齐本会话新增五个烟测页面的 lang=zh-CN，并在日期烟测断言七个功能区标签为中文。`/tmp/pdf-source-date-zh-red.log` 的语言断言先因缺失 lang 失败；修正后 `/tmp/pdf-source-date-zh-final/evidence.json` 为 ok:true，七个功能区标签均通过中文断言，恢复原两项真实操作并完成实际预览与独立回读，页面/HTTP 错误为空。中文窄屏和实际预览截图已目视；不以此最小续验冒称重跑完整日期复制链。

## 缺口口径修正

当前固定源 FormWidgetEditInput 与画布 onRects 协议只含 rect，不含目标页面；原 Widget 迁页仍是本地未支持边界，但尚未确认为该固定源已有功能，清单不再把它直接计作已确认源缺口。日期复制已不再列为全缺；任意复杂日期行为及属性编辑仍开放。
