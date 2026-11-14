# 监视窗口独立built验收

只使用root已冻结dist，`node smoke/workbook-watch-window-built-smoke.mjs`，默认4263端口，可通过WATCH_WINDOW_SMOKE_PORT覆盖；不构建。

本地真实HTTP XLSX/context fixture。保护表30格选区逐次20/30/去重、格式化显示值/公式、800ms键盘焦点、关闭重开保持、删除项、跨表稳定、只读history/draft/status与真实下载SHA不变；可编辑场景独立改输入与公式重算/Undo、插行后按原坐标监视、rename保sheetId、删表失效/Undo、reload与新revision清会话。编辑阶段有真实编辑，不能冒充零修改。全程不按保存，save0。

每case立即写cases.json（含行文字、截图路径/SHA）；每次实际JS响应HTTP200/磁盘SHA校验立即写assets.json。最终源文件与下载保存，输出临时目录；失败截图/阶段保留，先定位不放宽断言。授权/修订为夹具，不证明生产鉴权/桌面Excel或保存回写；该功能仅会话，不新增文件协议。

`WATCH_WINDOW_FROM=tail`仅续跑rename前置与reload/newrevision隔离，删表UI被独立官方popup隐藏阻挡，明确不伪称UI通过；真实main公开facade delete+Undo另有窄证据。`WATCH_WINDOW_FROM=saved`单独非native built harness，真实UI改值/一次save（无editorURL）后grid锁、面板增删关闭、真实Ribbon再开且状态不变；只导入实际构建公开模块，无产品debug后门。等待root最新dist才运行。

PC窗口布局可设置`WATCH_WINDOW_VIEWPORTS=1440x900,320x640,640x360,390x320,1440x360`，在原保护表阅读流程中分别检查空列表和30项列表，并为夹具D5/F5加入长值/长公式。检查真实DOM主题、窗口边界、单行按钮、列语义、所有可用按钮和表格区域的Tab往返/中心命中/焦点环、Home/End首尾、归零后的ArrowRight移动、Escape返回入口及切换Ribbon后的关闭焦点；布局操作前后localStorage必须一致，随后继续原9个行为场景。小视口依赖表格内部横纵滚动，不宣称一屏显示全部列或全文。

`WATCH_WINDOW_OUTPUT`指定一个不存在的输出目录，默认仍用随机临时目录；`WATCH_WINDOW_EXPECTED_MANIFEST`可固定构建SHA。新增逐phase布局JSON、evidence.json、响应大小、浏览器console错误和失败HTTP检查，结束时确认manifest未变化。保存后fixture分支也写evidence.json及来源文件，但其save应答为fixture，不代表实际生成了新XLSX。构建或任何共享smoke运行期间，不得修改产品源码、static或共享检查器；全部终态后才修改并重跑。
