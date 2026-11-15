// From the pinned GenOffice Slides renderer components/Ribbon.tsx.
/** Mini table thumbnail of a preset style (colors match the engine-side TABLE_STYLE_PRESETS literals) */
export function TableMiniPreview({
  header,
  band,
  rowLine,
  gridLine,
  outline,
}: {
  /** Header row background color */
  header?: string
  /** Banded stripe color (rows 2/4) */
  band?: string
  /** Horizontal line color between rows */
  rowLine?: string
  /** All-gridlines color (horizontal + vertical) */
  gridLine?: string
  /** Outer border color */
  outline?: string
}) {
  const W = 44
  const H = 26
  const rows = 4
  const cols = 3
  const rh = H / rows
  const cw = W / cols
  const hLines = [1, 2, 3].map((i) => i * rh)
  const line = gridLine ?? rowLine
  return (
    <svg width={W} height={H} shapeRendering="crispEdges" aria-hidden>
      <rect x={0} y={0} width={W} height={H} fill="#fff" />
      {band &&
        [1, 3].map((r) => <rect key={r} x={0} y={r * rh} width={W} height={rh} fill={band} />)}
      {header && <rect x={0} y={0} width={W} height={rh} fill={header} />}
      {line &&
        hLines.map((y) => (
          <line key={y} x1={0} y1={y} x2={W} y2={y} stroke={line} strokeWidth={1} />
        ))}
      {gridLine &&
        [1, 2].map((c) => (
          <line key={c} x1={c * cw} y1={0} x2={c * cw} y2={H} stroke={gridLine} strokeWidth={1} />
        ))}
      <rect
        x={0.5}
        y={0.5}
        width={W - 1}
        height={H - 1}
        fill="none"
        stroke={outline ?? '#E3E3E3'}
        strokeWidth={1}
      />
    </svg>
  )
}
