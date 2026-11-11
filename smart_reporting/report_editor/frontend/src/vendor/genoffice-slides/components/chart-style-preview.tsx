/** Extracted from GenOffice Ribbon.tsx at f8c17004. SVG body and matching logic unchanged. */
import type { ReactNode } from 'react'
import type { ChartStyleInfo } from '@genoffice/pptx-render'

interface ChartStylePreset {
  key: string
  label: string
  style: {
    legendPos: 'b' | 't' | 'r' | 'l' | 'none'
    dataLabels: boolean
    gridlines: boolean
    gapWidthPct: number
  }
}
/** Whether the current chart style matches a preset (bar width compared only for bar-family charts). */
export function chartPresetActive(info: ChartStyleInfo | null | undefined, p: ChartStylePreset): boolean {
  if (!info) return false
  const s = p.style
  const barKind =
    info.kind === 'bar' ||
    info.kind === 'bar3D' ||
    info.kind === 'barStacked' ||
    info.kind === 'comboBarLine'
  return (
    info.legendPos === s.legendPos &&
    info.dataLabels === s.dataLabels &&
    info.gridlines === s.gridlines &&
    (!barKind || (info.gapWidthPct ?? 150) === s.gapWidthPct)
  )
}

/** Style preset thumbnail (draws a bar/line/pie sample per the current chart type). */
export function ChartStyleThumb({
  kind,
  style,
}: {
  kind?: ChartStyleInfo['kind']
  style: ChartStylePreset['style']
}) {
  const W = 64
  const H = 40
  const C1 = '#4472C4'
  const C2 = '#ED7D31'
  const plot = { x: 5, y: 4, w: W - 10, h: H - 9 }
  if (style.legendPos === 'b') plot.h -= 6
  else if (style.legendPos === 't') {
    plot.y += 7
    plot.h -= 7
  } else if (style.legendPos === 'r') plot.w -= 13
  else if (style.legendPos === 'l') {
    plot.x += 13
    plot.w -= 13
  }
  const els: ReactNode[] = []
  const family =
    kind === 'line' || kind === 'area' || kind === 'scatter' || kind === 'radar'
      ? 'line'
      : kind === 'pie' || kind === 'pie3D' || kind === 'doughnut'
        ? 'pie'
        : 'bar'
  if (style.gridlines && family !== 'pie') {
    for (let i = 1; i <= 3; i++) {
      const y = plot.y + (plot.h * i) / 4
      els.push(
        <line
          key={`g${i}`}
          x1={plot.x}
          y1={y}
          x2={plot.x + plot.w}
          y2={y}
          stroke="#DADADA"
          strokeWidth={0.8}
        />,
      )
    }
  }
  if (family === 'bar') {
    const vals: Array<[number, number]> = [
      [0.55, 0.35],
      [0.8, 0.5],
      [0.65, 0.9],
    ]
    const slot = plot.w / 3
    const barW = Math.min(slot / (2 + style.gapWidthPct / 100), slot * 0.45)
    vals.forEach(([a, b], i) => {
      const gx = plot.x + i * slot + (slot - barW * 2) / 2
      const draw = (v: number, off: number, color: string, key: string) => {
        const h = plot.h * v
        els.push(
          <rect
            key={key}
            x={gx + off}
            y={plot.y + plot.h - h}
            width={barW}
            height={h}
            fill={color}
          />,
        )
        if (style.dataLabels)
          els.push(
            <circle
              key={`${key}d`}
              cx={gx + off + barW / 2}
              cy={plot.y + plot.h - h - 2.5}
              r={1.1}
              fill="#777"
            />,
          )
      }
      draw(a, 0, C1, `b${i}a`)
      draw(b, barW, C2, `b${i}b`)
    })
  } else if (family === 'line') {
    const mk = (vals: number[], color: string, key: string) => {
      const pts = vals.map(
        (v, i) => [plot.x + (plot.w * (i + 0.5)) / vals.length, plot.y + plot.h * (1 - v)] as const,
      )
      els.push(
        <polyline
          key={key}
          points={pts.map((p) => p.join(',')).join(' ')}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
        />,
      )
      if (style.dataLabels)
        pts.forEach((p, i) =>
          els.push(<circle key={`${key}d${i}`} cx={p[0]} cy={p[1] - 2.5} r={1.1} fill="#777" />),
        )
    }
    mk([0.3, 0.55, 0.45, 0.8], C1, 'l1')
    mk([0.15, 0.35, 0.6, 0.5], C2, 'l2')
  } else {
    const cx = plot.x + plot.w / 2
    const cy = plot.y + plot.h / 2
    const r = Math.min(plot.w, plot.h) / 2 - 1
    // Main circle + 120° sector (clockwise from 12 o'clock)
    els.push(<circle key="p1" cx={cx} cy={cy} r={r} fill={C1} />)
    const a = ((-90 + 120) * Math.PI) / 180
    els.push(
      <path
        key="p2"
        d={`M ${cx} ${cy} L ${cx} ${cy - r} A ${r} ${r} 0 0 1 ${cx + Math.cos(a) * r} ${cy + Math.sin(a) * r} Z`}
        fill={C2}
      />,
    )
    if (kind === 'doughnut')
      els.push(<circle key="ph" cx={cx} cy={cy} r={r * 0.45} fill="var(--surface, #fff)" />)
    if (style.dataLabels) {
      els.push(<circle key="pd1" cx={cx - r * 0.45} cy={cy + r * 0.2} r={1.1} fill="#fff" />)
      els.push(<circle key="pd2" cx={cx + r * 0.5} cy={cy - r * 0.3} r={1.1} fill="#fff" />)
    }
  }
  // Legend dots
  if (style.legendPos !== 'none') {
    const horiz = style.legendPos === 'b' || style.legendPos === 't'
    const ly = style.legendPos === 'b' ? H - 4 : style.legendPos === 't' ? 4 : H / 2 - 3
    const lx = style.legendPos === 'r' ? W - 9 : style.legendPos === 'l' ? 4 : W / 2 - 7
    els.push(<rect key="lg1" x={lx} y={ly - 1.5} width={5} height={3} fill={C1} />)
    els.push(
      <rect
        key="lg2"
        x={horiz ? lx + 9 : lx}
        y={horiz ? ly - 1.5 : ly + 4.5}
        width={5}
        height={3}
        fill={C2}
      />,
    )
  }
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden>
      {els}
    </svg>
  )
}
