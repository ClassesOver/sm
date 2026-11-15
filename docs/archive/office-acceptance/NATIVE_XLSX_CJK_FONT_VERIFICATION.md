# XLSX 中文字体菜单与真实保存验收

字体菜单保留已有西文字体，新增7项。显示名区分内置资源与系统字体，值使用实际font family：

| 菜单显示 | family |
| --- | --- |
| 思源黑体（内置） | Noto Sans CJK SC |
| 思源宋体（内置） | Noto Serif CJK SC |
| 宋体（系统字体） | SimSun |
| 黑体（系统字体） | SimHei |
| 微软雅黑（系统字体） | Microsoft YaHei |
| 楷体（系统字体） | KaiTi |
| 仿宋（系统字体） | FangSong |

ribbon仅扩展choice的label/value结构；实际保存仍通过原有font-family命令与格式差分。菜单新case真实RED `/tmp/workbook-cjk-font-menu-red.log`后，与既有菜单控制合计2项GREEN `/tmp/workbook-cjk-font-menu-green.log`。真实Univer range按菜单选择7种family、readBackSnapshot、applyCellEdits保存及styles字体表读回1项GREEN `/tmp/workbook-cjk-font-save-green.log`。类型检查`/tmp/workbook-cjk-font-final-types.log` exit0，仅做定向测试，未重跑完整套件。

root接入共享CSS并在createUniver前等待两SC内置字体加载，避免首次canvas布局缓存fallback字体。最终统一构建`/tmp/office-chart-cjk-caladea-final-build.log` exit0、40.68s，budget/contract均exit0，未提高cap。

`node smoke/workbook-cjk-font-built-smoke.mjs`最终纯UI验收session4393 exit0，日志`/tmp/workbook-cjk-font-built-final.log`：

- Noto Sans CJK SC及Noto Serif CJK SC均FontFace.status=loaded，document.fonts.check为true。
- 实际加载`NotoSansCJKsc-Regular-subset-CI7WjJWU.woff2`和`NotoSerifCJKsc-Regular-subset-DE8BO6ke.woff2`，HTTP200且SHA与磁盘一致。
- 真实goto A1:A7、菜单label检查、选择各family，保存的applyCellEdits仅写style.fontFamily；Python/openpyxl独立读回7个font.name精确一致，中文单元格值保留。
- 修订2重开后，逐行UI字体选择框仍为对应family。228个JS实际HTTP200/SHA一致，pageErrors=[]。
- 最终main`BnjejPFA`、XML parser`CSnIWqZm`、engine`HRFOVe0o`、structure`iLMhKLk0`、chart references`DySJZa2v`。

截图`/tmp/workbook-cjk-font-built.png`已目视，7行中文正常显示，两内置行可见黑体/宋体字形区别。系统字体选项仅保存其准确family，实际显示依赖用户系统安装及浏览器回退；本验收不把系统字体误称为内置下载资源。HTTP context/save/revision由probe提供，文件处理为真实Python，不宣称生产HTTP端到端。
