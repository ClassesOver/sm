# 透视缓存来源工作表改名

固定来源：`/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`，`packages/xlsx-gateway/src/gateway/xlsx-sheets.ts:588` 的 `renameSheetInPivotCacheSource`，以及 `xlsx-gateway.ts:2136` 的缓存来源改名调用。

本地 `applySheetEdits` 原先只改写工作表、图表及定义名称引用，遗漏存续透视表的 `pivotCacheDefinition/worksheetSource@sheet` 普通名称属性。现在收集与删除检查相同的缓存定义路径，为每个 rename 读取已替换版本再改写，避免后续 rename 覆盖先前修改；原删除检查保持原样。

公开同步纯函数 `renameSheetInPivotCacheSource(cacheXml, oldName, newName)` 可由引擎入口或 `pivot-cache-source` 子路径导入。沿用旧 helper 的 SpreadsheetML transitional/strict URI、忽略大小写、无命名空间 sheet 属性和单次实体解码语义；Saxes 完整验证 XML 后，仅替换目标属性值的原始字符跨度。保留前缀、单/双引号、空白、其他属性及非目标节点；注释、CDATA、外来同名节点/属性和重复编码的非匹配名称不改写。DOCTYPE 或损坏的后续 XML 拒绝整次操作，不能得到部分修改结果。新增名称按 XML 属性转义；字符引用保留制表和换行的值语义。

真实 ZIP 用 openpyxl 创建来源工作表、透视表、缓存、关系及无关工作表。默认 namespace、alias、strict、实体/单引号及两次 rename 的 5 个测试先 RED：`/tmp/pivot-rename-red.log`。EntrySource 既有前缀规范化仍存在，ZIP 比较基于其读取后的 XML；纯 helper 另行断言非目标字节完全保留。

最终 10 个新测试通过：`/tmp/pivot-rename-final-green.log`，包含改名后另一次删除新名称仍被依赖检查拒绝、损坏 XML/DTD 不产生输出等。既有透视来源删除及 sheet-ops 共 32 个测试在 `/tmp/pivot-rename-green.log` 通过（该轮新增 alias 测试因未纳入 EntrySource 既有前缀规范化而失败，已修正断言后单跑新增测试）。引擎严格类型检查通过：`/tmp/pivot-rename-types.log`。

未运行全量测试、bundle/build，未提交推送，未修改前端；实际主界面与浏览器保存验证由 root 进行。同一计划改名与删除组合的最终保存校验由主界面验证覆盖。
