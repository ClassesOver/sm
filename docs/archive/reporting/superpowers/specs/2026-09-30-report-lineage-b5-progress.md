# Report Editor 数据追溯 B5 进度记录（第一增量）

日期：2026-09-30。状态：B5 前端来源交互主体落地（API client + 来源面板 + 工具栏入口 + 状态体系）；真实浏览器联调与正文级入口随 B6/G9。

上游：计划 B5、b1~b4 进度记录（后端 API 已全部就绪）。

## 已完成

| 项 | 实现 | 测试 |
| --- | --- | --- |
| API client 扩展 | `api.ts`：sources/datasetPreview(+cursor/columns)/datasetDownloadUrl/facts/factDetail/charts/chartSource/computations/computationDetail；全部支持 AbortSignal（切换对象取消旧请求） | `trace-panel.test.ts`（URL 拼装、编码、错误码透传） |
| 来源面板 | `trace-panel.ts`（复用 createModal wide + focus-trap + Esc）：四个 tab（数据快照/事实/图表/计算记录）；数据集预览分页表格（nextCursor 续翻、行号窗口说明、预算截断标注）；下载原始前 HEAD 探测权限（403 → 明确文案，不让浏览器跳 JSON 错误页）；图表来源详情（数据集、转换说明、作图数据表格 + offset 分页）；计算记录详情（方法、执行环境、核对/复算状态、输出事实可点跳事实详情）；事实详情（displayValue、公式、输入事实链跳转、告警） | 9 例（列表渲染、空索引、403、重试、分页表格、tab 切换取消） |
| 状态体系 | loading（切换即取消旧请求）/ empty（"当前修订没有来源索引"如实提示）/ 404 source_missing / 403 无权限（无重试按钮）/ 409 fact_binding_unavailable / 410 过期 / 完整性失败 / 413 超限 / 5xx+网络（带重试按钮）——稳定错误码 → 中文文案映射 | 同上 |
| 工具栏入口 | shell.ts "来源"按钮（database 图标，aria-label）；main.ts 装配（client 声明后挂接）；CSS（tab/条目/表格/状态区，sticky 表头、移动换行） | shell.test.ts 图标清单更新 |
| 键盘可访问性 | createModal 既有能力复用：focus-trap、Esc 关闭、关闭后焦点返回触发按钮；tab 按钮原生 button 元素 + aria-selected；状态区 role=status aria-live | 模式复用 |

验证（2026-09-30）：前端 `npm test` 237 passed（34 文件，含 9 个新 trace 面板测试）；`npm run build`（tsc --noEmit + vite）通过；`npm run check:budget` 通过。

## B5 剩余（下一增量/随批次）

1. **正文级入口**：指标/单元格/图题旁的"查看来源"定位（需要 B6 subject 绑定与 stale 判定）；当前入口为工具栏全局面板。
2. **真实浏览器联调**：`smoke` 需要真实编辑会话 URL（已发布报告 + 有效 grant）——随 B6 完成草稿状态联调或 G9 真实跑批执行（fixture-server 只验证界面，授权与真实文件必须走真实后端，计划 10.1）。
3. **移动端完整宽度抽屉**：当前为 modal wide；计划 B5-6 的小屏完整宽度优化随 UI 打磨。
4. **复制摘要仅复制授权字段**（计划 B5-6）：面板无复制功能前不适用，随复制功能加入时实现。

## 设计决定（如实记录）

- 面板用 modal（复用 createModal 全部可访问性能力）而非独立侧栏——与 share/history/export-settings 面板一致，避免发明第二套容器；outline 式抽屉留给正文级入口（B6）。
- 下载按钮先 HEAD 探测：避免分享会话点击后浏览器直接展示后端 JSON 错误体；403 时在面板状态区给出原因。
- 事实 tab 第一版展示分析级清单：单事实定位入口通过计算记录的输出 refs（factKey 可点）——正文数字直达事实需要 subject 绑定（B6），不在面板内伪造定位。
- tab 切换 abort：AbortController 在每次 beginRequest 时重建，旧请求的迟到响应被丢弃（测试覆盖）。
