# PDF 已保存绘图逻辑删除验收

2026-11-10；固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。原始素材为固定 PDF drawing/save writer、批注字典/Annots、关系引用图与实际输出文件。Web 绘图列表是宿主适配，不声称复刻全部桌面对象操作。

支持 Square/Circle/Line/Ink/Polygon/Caret 的安全子集。以来源 SHA、页身份、原始批注槽位派生身份及字典 SHA 核验，绝不按位置或文字搜索对象。删除复用严格 Annots 变换与幸存批注、AP、正文、资源、表单、便签身份核验。

全引用图 census 对关联、共享、direct、锁定、签名/Perms、未知关系/扩展及无法确认外观保持只读，列表解释原因。能力只在至少一个安全对象存在时开放。来源伪造、过期字典、裁切/尺寸/原位改字混用拒绝。

UI 支持逐项暂存/撤销、全局历史与刷新恢复、删除区域提示、实际预览、保存下载及新修订重开。删除只是逻辑移除，不是安全擦除；不保证底层旧对象字节不可恢复。

## 证据

- saved-drawings/drawings 引擎9项；六种子类型逐个实际删除，两个完全重叠的相同 Line 只删除指定身份；幸存 ref/dictHash/AP、正文资源、表单、便签与旋转/顺序保留，危险与伪造请求拒绝。
- 前端 saved-drawings/pdf-operations 19项与 TypeScript 检查。
- 根集成新增混合 drawing/note 的日期追加顺序回归，含相同文字与位置的旧便签；13项唯一 drawing/saved-drawing/note-timestamps 检查通过，另14项已保存/本地回复回归通过。日期规范化只改实际新增便签，不假设所有便签位于连续尾部。
- `frontend/smoke/pdf-saved-drawings-smoke.mjs` 使用生产静态资源与真实 Python/打包 bridge，验证精确双胞胎删除、历史/恢复、预览、下载、重开与独立 pypdf 回读。注册路由为测试桩，不证明生产 SQL/鉴权。

保存绘图移动/改样式、复杂关系来源删除、Stamp/图像等其余类型，以及完整 PDF、桌面、生产和完整镜像验收仍开放；功能开关保持关闭。

## 集成验收记录

Standard 与 Slides 前端构建、配置的 Standard budget 通过；PDF strict tsc 仅保留六项既有宿主/未打包 UI 声明诊断，无新增错误。应用 Python Ruff 与 diff 检查通过，未重复全仓测试。

打包运行时在 `node:22-slim --network=none` 执行实际修改成功，伪造字典/非法结构请求非零退出且无输出文件；独立 pypdf/python-pptx 检查正文、批注数量、网格与空白新列。证据 `/workspace/scratch/pr210-next/offline/independent.json`。此结果不代替完整应用镜像、数据库或鉴权验收。

生产静态 Chromium 浏览器已通过重叠双绘图精确删除、逐项/全局撤销重做、刷新恢复、实际预览、验收失败仍可下载、保存重开及只读隔离；独立 pypdf 确认3页、剩余1条 Line、正文与表单值不变。证据 `/workspace/scratch/pr210-saved-drawings/evidence.json`。
