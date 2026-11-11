# XLSX 活动行列突出显示验收

2026-11-10 完成。限定交付为 View 的活动行列阅读高亮；不代表全量 XLSX
对齐。实现/源码归属/调查过程见 `NATIVE_XLSX_CROSS_HIGHLIGHT_INVESTIGATION.md`
和 `frontend/src/workbook-vendor/SOURCE.md` 独立 host module 段。

## 实现与边界

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`
`apps/sheets/src/renderer/cross-highlight.tsx` 迁入宿主独立模块。
实际 Worksheet WeakMap 隔离多实例；Univer 官方 selection command 更新主活动格；
canvas viewport 分段覆盖冻结窗格，打印时不绘制。阅读偏好独立于编辑权限，
主题刷新与 mount/dispose 清理受控；不写单元格样式、snapshot、NativeDraft、
保存协议或历史。RTL 实际像素发现上游负行宽，已以反序边界 min/max 修复。
最终宿主 helper SHA256：
`115e9a92f5aa1e303d69025c960e4158188bb5835e7157ea8919698aabeb6541`。

## 定向回归

- helper/Ribbon 初验 11 passed，main 1 passed；新增只读恢复/存储异常 2 passed。
- RTL 反序几何向量先 RED（1 failed），修后 5 个几何向量 GREEN；隐藏活动
  行/列零尺寸向量单独 GREEN，不虚构高亮带；列上下边界保持原样。
- main 真正 Univer 集成核对完整 snapshot、undo/redo、草稿和保存标签不变。
- 生命周期向量覆盖实例 ID 冲突、来源替换、销毁隔离、打印禁画及异常存储。
- root 最终统一构建 `/tmp/office-row-distribute-cross-highlight-build.log`
  exit 0（40.25s，含 TypeScript）；budget/contract exit 0，未提高预算。
  高亮独立 chunk，避免扩大 workbook-main 预算。

仅定向测试，未重复完整测试。

## 独立构建浏览器验收

命令：`node smoke/workbook-cross-highlight-built-smoke.mjs`，默认端口 4243。
最后进程 session 82482 已明确取得 exit 0；最终日志
`/tmp/xlsx-cross-highlight-built-smoke.log`，结尾 `ok=true`。

| 场景 | 实际证据 |
| --- | --- |
| 普通 C5 | 行/列源色块混色、非目标色块不变，关闭恢复均 100% |
| 冻结 C3 后 C5 | 冻结两侧行列色块均 100% |
| 150% 缩放 | 实际色块尺寸扩大，混色/恢复均 100% |
| RTL | 实际反向列序下行列混色/恢复均 100% |
| 从 D6 反向扩选 C5:D6 | 原生剪贴板确认实际矩阵；D6 行列高亮，C5 行列不高亮，全部 100% |
| Z25001 远处空白格 | 原生方向键滚入后 85182 高亮像素，列/行带长 664/1363px；关闭恢复 100% |

检测使用真实 PNG 像素，对源色块向内 2px 实色区域断言预期 alpha 混色，
不把主动描边误当纯填色；填色阈值 >96%、关闭恢复 >99.5%，最终均 100%。
未用纯几何或截图目视替代上述像素断言。

230 个构建 JS 响应为 200 且 SHA 与静态文件相符，pageErrors=[]。
偏好刷新恢复；完整 localStorage（仅排除阅读偏好）、历史按钮状态、
保存标签精确不变；save 请求 0。真实宿主 XLSX 下载入口前后下载文件与
来源字节 SHA 一致：
`e665e4fae5b03534db912e65f188055a84553d1eb8aefe390144cc4397c11e2f`。
HTTP API/context 为本地夹具，静态文件代理到真实 preview；不冒计生产
HTTP 授权/修订系统或桌面 Excel 等价。打印禁画为单元证据，未执行独立打印。

## 留存产物与未解决差异

`/tmp/cross-highlight-built-AAfR14` 包含各场景 `*-off.png`、`*-on.png`、
`*-restored.png`，以及 `source.xlsx`、`downloaded-before.xlsx`、
`downloaded-after.xlsx`。root 已目视 `rtl-on.png`。

原失败日志保留：`/tmp/xlsx-cross-highlight-built-rtl-failure.log`（真实 RTL
缺陷）、`/tmp/xlsx-cross-highlight-built-far-navigation-failure.log`（定位只选
未滚动）、`/tmp/xlsx-cross-highlight-built-reload-fixture-failure.log`（HTTP
测试夹具 reload 映射缺失）。下载夹具改真实 HTTP，未放宽下载/SHA 断言。

远处 goto 只选不滚动仍独立待查，本轮未修改；其后用真实方向键滚入，
再验证高亮。该事实不影响屏外目标应不绘制的高亮契约，但不能据此把
定位导航视为对齐。独立调查见 `NATIVE_XLSX_GOTO_SCROLL_INVESTIGATION.md`。
