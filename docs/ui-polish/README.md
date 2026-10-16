# Report Editor UI 打磨（2026-10-16）

本轮对 `smart_reporting/report_editor` 前端做了系统性 UI 打磨，共约 90 轮迭代。
改动集中在 `frontend/src/style.css`（设计 token + 动效语言）与少量 TS（骨架屏、无障碍）。

## 设计系统

- **颜色 token**：`:root` 定义 15 个颜色 token，收敛 400+ 处硬编码
- **字号**：7 档（11/12/13/14/16/20/24）
- **圆角**：6 档（6/8/10/12/14/999）
- **z-index**：10 个语义层叠 token
- **断点**：语义档位（640/768/900/1100/1200/1600）

## 动效语言

- **时长四档**：`--motion-instant` 90ms / `--motion-fast` 150ms / `--motion-base` 250ms / `--motion-slow` 400ms
- **缓动三档**：`--motion-ease-out` / `--motion-ease-in-out` / `--motion-spring`
- **语义原语**：`motion-fade-in` / `motion-rise-in` / `motion-slide-in-left` / `motion-pop-in`
- 31 处 transition 收敛到 `--motion-fast`；循环动画（spin/pulse/shimmer）保留
- `prefers-reduced-motion` 全局兜底

## 主要改进

1. 证据浏览器：来源卡片类型色顶栏、悬浮上浮、stagger 入场
2. 来源目录：分组折叠、滚动吸顶、搜索匹配计数、骨架屏、类型色徽标
3. 详情页：信息卡片、关系图点阵底纹、详情骨架屏
4. 主编辑器：引用标记 hover、大纲过渡、表格行 hover、图片圆角阴影
5. 无障碍：跳过导航链接、键盘导航、对比度修复、读屏优化
6. 移动端：抽屉滑入、触摸目标、底部操作栏

## 效果演示

- `ev-motion-unified.webm`：统一动效语言演示（页面转场/弹窗/列表入场）
- `ev-animations-r1-r9.webm`：动画轮次演示
- `final-desktop.png`：桌面主编辑器
- `final-evidence.png`：证据浏览器
- `final-mobile.png`：移动端

## 验证

- `tsc --noEmit` 通过
- 全量 622 测试通过
