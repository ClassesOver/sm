# XLSX 定位目标滚动验收

2026-11-10 完成已确认的 goto 只选择不滚动缺口。固定源码、原始复现与
因果追溯见 `NATIVE_XLSX_GOTO_SCROLL_INVESTIGATION.md`；此文限定导航补齐，
不代表完整 XLSX 对齐或全局在线编辑授权变更。

## 变更与来源

保留 main 原有引用解析、切表、`setActiveRange` 和关闭模态框后官方焦点
交接；新增宿主 `workbook-goto-reveal.ts`，复用固定 GenOffice
`f8c17004fb730df11f0f743164ffd8b4281bb38c` 的
`univer-sync.ts:917 revealCellBelowFreeze`。使用官方 `scrollToCell` 和
`getVisibleRange` 做实际视口校正，避免靠默认行高或缩放猜坐标。所有冻结
viewport 通过官方 Map 检查；RTL先等原生reveal再决定是否需要跳转。

按实例管理 generation/计时器，新导航、来源替换和 dispose 取消旧操作；
切表/改变目标选区后停止旧校正，迟到失败不覆盖新结果。只有检查目标
可见后报告“目标已显示”；无变化/异常保留活动选区并给出未显示原因。
不改高亮模块，不新增保存操作、不引入源应用 lazy loading 系统。

SOURCE 文档记录上游整文件 SHA
`677f67710889e5d17e5e643177090757cd89534997589930976e78dd4e8cbf4e`，
宿主 helper SHA
`49b94e723cf395b5ea580d5069ad4514392a7366c877f8600187ad463bf0a35a`；
宿主文件不混入 vendor 目录 hash manifests。

## 定向验证

- helper RED（模块不存在）→ 7 GREEN：远处目标、冻结已可见不跳、实测冻结
  偏移校正、RTL等待、失败不宣称成功、多实例/新导航/销毁、来源替换。
- main 真实接线 RED 明确 reveal 调用0次 → 3 GREEN：只读跨表选择与显示，
  完整snapshot/草稿/历史/保存态不变，未显示和接口异常的真实反馈。
- 迟到失败1 GREEN；原焦点/取消/已定义名称兼容4 GREEN。
- `tsc --noEmit` session76271 exit0。root最终统一frontend构建
  `/tmp/office-autofit-goto-build.log` exit0（40.76s），budget/contract exit0，
  未升预算或额外拆chunk。未重复完整测试。

日志：`/tmp/xlsx-goto-reveal-green.log`、
`/tmp/xlsx-goto-main-feedback-green.log`、`/tmp/xlsx-goto-stale-green.log`、
`/tmp/xlsx-goto-focus-green.log`。旧失败日志按原路径保留。

## 严格 built 浏览器验证

`node smoke/workbook-goto-scroll-built-smoke.mjs`，端口4243；session66605
明确 exit0，最终日志 `/tmp/xlsx-goto-scroll-built-smoke.log` 结尾 `ok=true`。
五种真实 XLSX 工作表全部启用 sheetProtection；每场通过公开定位框直接
导航 `Sheet!Z25001`，**不发送 ArrowDown/ArrowUp 或其他键盘滚动**。
必须先等精确“目标已显示”反馈，再以真实画布 PNG 像素验证目标行列确在
可见区域，关闭后像素恢复。不是仅核对名称框、纯几何或截图目视。

| 来源 | 实际高亮像素 | 最大列/行带像素 | 关闭恢复 |
| --- | ---: | --- | --- |
| Plain | 85182 | 664 / 1363 | 100% |
| Frozen（两行自定义42/35pt、A/B列18/22宽） | 85268 | 665 / 1363 | 100% |
| Zoom150 | 127518 | 663 / 1346 | 100% |
| RTL | 85810 | 664 / 1362 | 100% |
| Far空白目标 | 85182 | 664 / 1363 | 100% |

230个静态JS响应200并匹配本地构建SHA，pageErrors=[]；刷新恢复阅读偏好；
完整localStorage（只排除阅读偏好）、undo/redo按钮状态、保存标签精确不变，
save请求0。真实宿主XLSX下载入口 before/after文件与来源SHA相同：
`62309006fa04bad848c07b784987df0ff3564e90cbd488ce4fb0be0445418bbe`。

产物 `/tmp/goto-scroll-built-o6aIj7` 含source.xlsx、downloaded-before.xlsx、
downloaded-after.xlsx及每场off/on/restored PNG。推荐目视：
`frozen-distant-on.png`（冻结1/2行仍见，名称框Z25001且目标完整可见）、
`rtl-distant-on.png`。执行agent已目视冻结图。

## 范围与现有应用限制

最初使用顶层 `editingEnabled=false` 的API上下文时，既有
`native-office-view.ts:54` 直接禁止整个在线编辑器挂载，无法出现Ribbon；
失败截图 `/tmp/goto-scroll-built-1dkeNg/failure.png` 与日志
`/tmp/xlsx-goto-scroll-built-feature-gate-failure.log` 已保留。
因此最终built使用 **editingEnabled=true且实际源表受保护** 的阅读场景，
不宣称顶层功能关闭时UI仍可导航。main层false的只读导航由定向集成覆盖。
本轮未修改该全局功能门禁，也未放宽Home就绪/可见反馈/像素/下载断言。

浏览器HTTP context/来源由真实本地HTTP夹具提供，静态资源来自真实preview；
不冒计生产授权HTTP、桌面Excel、浏览器打印或所有编辑中跳转情形等价。
