# Word 当前节页面边框快捷项（2026-11-13）

固定参照 `/home/junge/pros/genoffice-source-full`，提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。`ribbon-design-tab.tsx:474–493` 的“方框／无”是实际源入口：“方框”先移除已有 `pageBorderProps`，再设置 `pageBorder:true`；“无”设置 false。本批沿同样语义接通“设计→页面边框”，限定光标所在节。

## 实现与边界

复用现有 sectionId／expectedSectionSha256、`setSectionLayout`、NativeDraft／UndoRedo／恢复、原 `applySectionSettings` 和 `pageBordersXml`；后两个函数所在文件与固定源逐字节相同，见 `/dev/shm/office-next-word-page-borders-20261113/source-evidence.json`。没有另建边框编码器或导出链。

协议仅扩展 `pageBorder:boolean`，不接受任意 pageBorderProps/XML。“方框”重置来源自定义属性为源默认四边 single、0.5pt、距纸边24pt；其它节设置合并不清除原自定义框。“无”移除边框。纯边框操作保留非目标core与其它包部件；与人工正文操作组合时沿既有正文修订元数据语义。原生写后独立回读验证目标节状态和默认框确已应用。

多节中只改光标节；待插入分节符等既有guard保留。受保护来源与过期节身份拒绝写入。菜单关闭及选择相同默认值不新建历史，保存期间禁用并给出原因。完整“边框和底纹…”对话框仍明确禁用，不宣称艺术框、任意边宽/颜色、全篇或首页适用范围已经接入。

实际边框展示使用源 `PaginationPreview`，按节分页验证；本批未新增普通连续编辑画布的边框层，不把源第一页画布逻辑推成完整多节显示。菜单提示可进入分页预览核对各节边框。

## 定向验证

证据根 `/dev/shm/office-next-word-page-borders-20261113`：

- `frontend-red.log`：三个真实失败，快捷菜单缺失、默认框/清除未接线、恢复校验不接受pageBorder。
- `native-red.log`：两节有效写入不支持失败，四个非法输入既有拒绝通过。
- `native-green-01.log`：边框已实际写入，但两例暴露core被不必要更新；随后仅把pageBorder纳入已有markup-only分类，保留旧其它layout语义。
- `frontend-green-final.log`：新5例和旧section6例通过。其后按类型检查补齐fixture必需汇总字段并改helper为无`.ts`后缀的直接section导入；`frontend-typed-final.log` 对最终测试/模块重验5例通过。
- `native-green-final.log`：6例通过，覆盖尾/非尾节从已有自定义框→默认框→无、其它节与非目标包部件字节保留、非法值拒绝；`native-protected.log` 另1例通过，覆盖过期节和只读保护拒绝。没有重复完整测试套件。

以上只证明本节定向范围，完整HTTP保存、实际下载和分页预览身份另以本批冻结运行记录为准，不能由测试结果推定生产数据库授权或业务版式验收完成。

## 冻结 HTTP 验收补记

专项运行记录记载的唯一完整浏览器保存为修订4→5；实际 DOCX 为38156字节，SHA-256 `7186a44990d7573d088a1de7ecaa033bfae4e70d87d425de9326b6df6db134a8`。保存回执保留 `validation.ok=false/native_source_review_pending`，身份核验后的下载照常签发；这不代表业务验收通过。记录的独立回读为两节分别 defaultBox/none、人工 MANUAL/italic 保留及16个非目标 package 部件逐字节不变。实际分页预览按节显示边框；桌面和390px视口均有截图。

以上身份和回读结果来自原专项 `/dev/shm/office-next-word-page-borders-20261113/browser-frozen-01/` 运行记录。最终汇总时该目录已不在当前文件系统中，root 无法重新读取 DOCX、HTTP回执或资源清单，故保留专项原报告，不把 root 独立复核标为通过；没有重复保存以重造证据。
