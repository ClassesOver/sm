# 监视窗口独立built验收

只使用root已冻结dist，`node smoke/workbook-watch-window-built-smoke.mjs`，默认4263端口，可通过WATCH_WINDOW_SMOKE_PORT覆盖；不构建。

本地真实HTTP XLSX/context fixture。保护表30格选区逐次20/30/去重、格式化显示值/公式、800ms键盘焦点、关闭重开保持、删除项、跨表稳定、只读history/draft/status与真实下载SHA不变；可编辑场景独立改输入与公式重算/Undo、插行后按原坐标监视、rename保sheetId、删表失效/Undo、reload与新revision清会话。编辑阶段有真实编辑，不能冒充零修改。全程不按保存，save0。

每case立即写cases.json（含行文字、截图路径/SHA）；每次实际JS响应HTTP200/磁盘SHA校验立即写assets.json。最终源文件与下载保存，输出临时目录；失败截图/阶段保留，先定位不放宽断言。授权/修订为夹具，不证明生产鉴权/桌面Excel或保存回写；该功能仅会话，不新增文件协议。

`WATCH_WINDOW_FROM=tail`仅续跑rename前置与reload/newrevision隔离，删表UI被独立官方popup隐藏阻挡，明确不伪称UI通过；真实main公开facade delete+Undo另有窄证据。`WATCH_WINDOW_FROM=saved`单独非native built harness，真实UI改值/一次save（无editorURL）后grid锁、面板增删关闭、真实Ribbon再开且状态不变；只导入实际构建公开模块，无产品debug后门。等待root最新dist才运行。
