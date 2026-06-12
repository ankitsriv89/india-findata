/**
 * SectorHeatmap.tsx — D3 sector-performance heatmap (first D3 usage in repo).
 *
 * Recharts covers our line/bar/area needs, but a sized-and-coloured grid of
 * sectors is a custom visualisation that's far cleaner in D3.  This is the
 * canonical React + D3 integration pattern:
 *
 *   - React owns the <svg> element (via useRef) and the component lifecycle.
 *   - D3 owns everything *inside* the svg, run imperatively in a useEffect
 *     that re-fires whenever the data changes.
 *
 * We deliberately do NOT use d3 to mutate React-managed DOM outside the svg —
 * the two libraries share exactly one boundary (the svg node), which keeps the
 * mental model simple and avoids React/D3 fighting over the DOM.
 *
 * The grid: one rectangle per sector, laid out in a fixed number of columns,
 * coloured on a diverging red→white→green scale by average % change.
 */

import { useEffect, useRef } from 'react'
import * as d3 from 'd3'
import { useHeatmap } from '../../api/hooks'
import type { HeatmapCell } from '../../api/client'
import ChartWrapper from './ChartWrapper'
import './charts.css'

interface Props {
  date: string
  exchange?: string
}

const COLUMNS = 4
const CELL_H = 64
const GAP = 6

/**
 * Imperatively (re)draw the heatmap into `svg` for the given cells.
 * Pulled out of the component so the useEffect body stays readable.
 */
function draw(svgEl: SVGSVGElement, cells: HeatmapCell[]) {
  const svg = d3.select(svgEl)
  svg.selectAll('*').remove() // clear previous render (data changed)

  const width = svgEl.clientWidth || 480
  const cellW = (width - GAP * (COLUMNS - 1)) / COLUMNS
  const rows = Math.ceil(cells.length / COLUMNS)
  const height = rows * CELL_H + (rows - 1) * GAP
  svg.attr('height', height)

  // Diverging colour scale centred at 0% — red for down, green for up.
  // The domain is clamped to ±3% so typical daily moves use the full range.
  const maxAbs = Math.max(3, d3.max(cells, d => Math.abs(d.change_pct)) ?? 3)
  const color = d3
    .scaleLinear<string>()
    .domain([-maxAbs, 0, maxAbs])
    .range(['#e03131', '#f1f3f5', '#2f9e44'])
    .clamp(true)

  const g = svg
    .selectAll('g.cell')
    .data(cells)
    .join('g')
    .attr('class', 'cell')
    .attr('transform', (_d, i) => {
      const col = i % COLUMNS
      const row = Math.floor(i / COLUMNS)
      return `translate(${col * (cellW + GAP)}, ${row * (CELL_H + GAP)})`
    })

  g.append('rect')
    .attr('width', cellW)
    .attr('height', CELL_H)
    .attr('rx', 6)
    .attr('fill', d => color(d.change_pct))

  // Sector label (top-left of the cell)
  g.append('text')
    .attr('x', 8)
    .attr('y', 20)
    .attr('font-size', 11)
    .attr('font-weight', 600)
    .attr('fill', '#1a1a1a')
    .text(d => d.sector)

  // % change (centre-ish)
  g.append('text')
    .attr('x', 8)
    .attr('y', 42)
    .attr('font-size', 16)
    .attr('font-weight', 700)
    .attr('fill', '#1a1a1a')
    .text(d => `${d.change_pct >= 0 ? '+' : ''}${d.change_pct.toFixed(2)}%`)

  // Symbol count (bottom-right, muted)
  g.append('text')
    .attr('x', cellW - 8)
    .attr('y', CELL_H - 8)
    .attr('text-anchor', 'end')
    .attr('font-size', 10)
    .attr('fill', '#495057')
    .text(d => `${d.symbols} stk`)
}

export default function SectorHeatmap({ date, exchange = 'NSE' }: Props) {
  const { data, isLoading, isError } = useHeatmap(date, exchange)
  const svgRef = useRef<SVGSVGElement>(null)
  const cells = data?.cells ?? []

  useEffect(() => {
    if (svgRef.current && cells.length > 0) {
      draw(svgRef.current, cells)
    }
  }, [cells])

  return (
    <ChartWrapper
      title="Sector Heatmap"
      subtitle={`${exchange} · avg daily %change by sector · ${date}`}
      isLoading={isLoading}
      isError={isError}
      isEmpty={cells.length === 0}
    >
      {/* width:100% lets D3 read clientWidth for responsive cell sizing */}
      <svg ref={svgRef} width="100%" role="img" aria-label="Sector performance heatmap" />
    </ChartWrapper>
  )
}
