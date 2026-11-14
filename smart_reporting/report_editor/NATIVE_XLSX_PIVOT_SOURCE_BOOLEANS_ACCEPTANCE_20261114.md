# XLSX 透视源布尔类型专项验收

参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；本地 `1e4a0a34` 加当前工作区。日期 2026-11-14。

源布尔单元格此前在文件计算时被转为数字 1/0，导致预览与保存结果不同，例如混合 true、false、2、"3"、"text"、空值的求和从预期 5 变成 6。本批保留布尔类型，创建、受管刷新和仅缓存刷新均写入 b 记录；基项缓存读取接受 0/1/true/false 四种合法布尔写法。固定源 domain 的聚合排除数值运算中的布尔值、count 包含布尔值；其 gateway 也存在布尔转数字限制，本批明确修正该限制，未宣称原样迁移即可解决。

验证：

- 新增十一种聚合与受管刷新、仅缓存刷新共12项真实文件回归，先 RED12 后通过；缓存布尔字面量先 RED2 后通过。
- 最终定向引擎107项、前端78项通过；两端实际导入和测试闭包严格 TypeScript 检查通过。未重复完整套件。
- 独立 openpyxl、ZIP/XML 回读十二份 XLSX，确认源单元格及度量缓存保留布尔类型。十一种期望结果为 sum=5、count=5、countNums=2、average=2.5、product=6、min=2、max=3、var=0.5、varp=0.25、stdDev=√0.5、stdDevp=0.5；仅缓存刷新 sum=5。数字文本参与聚合是固定源 domain 策略，不是完整 Excel 算术等价声明。
- 同模型独立审查未发现本批重要遗留问题。本批无新 UI，无新增浏览器验收；未执行桌面 Excel、完整应用服务或真实 provider 链路。

另有三份实际诊断文件确认尚未修复的维度显示格式差异：0000 格式的 1 应显示 0001，1900 日期 45292 应显示 2024-01-01，1904 日期 0 应显示 1904-01-01；本地分别输出 1、45292、0。度量值 2 保持数值。参考期望来自已检查固定源 readPivotSourceGrid 的静态字面量分支及 numfmt 3.2.6 执行，未运行整个固定源 UI。已登记为 P12 partial，不计作通过；分组、计算字段和日期缓存投影需要共同设计。

证据在 `/tmp/xlsx-pivot-booleans-20261114/`：生成和独立回读脚本、十二份验收文件、三份格式差异文件、independent-readback.json、dimension-format-gap.json、RED/GREEN/最终测试和类型日志。source-binding.json 与 tested-sources/ 冻结本批代码实际字节；engine UPSTREAM-PATCHES 哈希同步，旧批身份保留。检查另发现清单中八条本批之外的历史条目与当前字节不符，已单列 preexisting-manifest-discrepancies.json，未改写或声称这些条目通过；本批相关条目均匹配。未提交、推送或部署；全域对齐继续进行。
