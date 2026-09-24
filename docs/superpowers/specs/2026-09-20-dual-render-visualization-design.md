# Dual-render Visualization Design

## Goal

Reporting supports Matplotlib static charts and Plotly interactive charts in the same report. The request selects `auto`, `static`, or `interactive`; `auto` lets the model choose per chart. PDF and Word remain deterministic static documents.

## Product Contract

- `visualizationMode` is a report-level preference with values `auto`, `static`, and `interactive`; the default is `auto`.
- Every chart has a `renderer` of `matplotlib` or `plotly`.
- Every chart always has a PNG/JPEG `sourcePath`. This is the authoritative fallback used by Markdown, PDF, Word, accessibility text, and visual review.
- A Plotly chart additionally has an `interactivePath` ending in `.plotly.json`.
- `static` only permits Matplotlib registrations. `interactive` asks the model to prefer Plotly but permits Matplotlib when the requested visual cannot be represented adequately. This is a preference, not a semantic failure gate.
- Business-semantic concerns remain soft warnings. File identity, path confinement, schema safety, and executable-content rejection remain hard gates.

## Data Flow

The visualization task receives the report preference. The model writes arbitrary Python within the existing signed workspace and chooses a renderer per chart. Matplotlib produces a raster. Plotly produces a constrained Plotly figure JSON plus a raster fallback.

`submit_visualization_charts` validates both files and persists their identities. The analysis manifest carries the renderer and optional interactive identity. Final Markdown continues to contain ordinary image syntax, so current PDF/Word rendering and Markdown editing remain unchanged.

The report editor document response exposes a hash-bound mapping from fallback image path to Plotly spec URL. The frontend lazily imports a locally bundled Plotly.js build and enhances matching images after Milkdown renders them. A fetch, validation, import, or render failure leaves the image intact.

## Plotly JSON Boundary

Only JSON is accepted. HTML and JavaScript artifacts are never accepted. The root object contains `data`, optional `layout`, and optional `config`. Validation enforces bounded bytes, nesting, trace count, and total array items. It rejects keys or string values that introduce executable or remote content, including `src`, external URLs, `javascript:`, event handlers, templates containing HTML, and Mapbox tokens.

The initial trace allowlist is `bar`, `scatter`, `scattergl`, `pie`, `heatmap`, `box`, `violin`, `histogram`, `waterfall`, `funnel`, and `indicator`. Unsupported traces may fall back to Matplotlib; expanding the allowlist requires contract tests.

## Static Fallback

Plotly JSON is the interactive description, but it never replaces the raster contract. The initial implementation does not install Kaleido in the sandbox. A Plotly chart's fallback may be produced by the same script with an installed static backend or by equivalent Matplotlib code. The submission metadata binds both artifacts to one chart and the same citations/dataset semantics.

Until Kaleido is deliberately admitted and sandboxed, prompt guidance must not claim that `fig.write_image()` is available. This avoids creating an undeclared Chrome execution dependency.

> **已取代（2026-09-24）：** 用户已拍板安装 Kaleido——`pyproject.toml` 新增 `kaleido>=1.4.0`，根 `Dockerfile` 在构建期经 `choreo_get_chrome` provision 专用 Chrome 并把 `fig.write_image()` 纳入冒烟检查；可视化 Coding 指令已改为"Plotly 的静态图使用 fig.write_image()（Kaleido 已随环境提供）"。本节"不安装 Kaleido / 不得声称 write_image 可用"两条仅保留为历史决策记录。注意边界：Chrome 只在报表宿主镜像提供；`docker/sandbox-tools` 镜像的 forbidden 列表仍含 kaleido，脚本执行路径若迁移需重新评估。

## Editor And Security

The editor serves specs only when their path, size, and SHA-256 match the published job. Responses use `application/json`, `nosniff`, `no-store`, and `Content-Security-Policy: default-src 'none'`. Plotly.js is bundled locally; CSP does not allow CDNs, inline scripts, external images, or frames.

Interactive charts are view enhancements, not editable Markdown nodes. Saving, history restore, search/replace, and export continue to operate on the fallback image Markdown. The frontend destroys stale Plotly instances before re-enhancing after a document replacement.

## Compatibility And Verification

Existing chart payloads deserialize as `renderer=matplotlib` and no interactive artifact. Existing reports render unchanged. Tests cover request defaults and overrides, chart pairing, unsafe JSON rejection, durable identities, manifest propagation, authenticated resource serving, lazy frontend enhancement, failure fallback, and unchanged PDF/Word image validation.

