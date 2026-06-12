/**
 * DualAxisChart.tsx — two series on independent Y-axes, with event annotations.
 *
 * The correlation explorer plots two arbitrary series whose units differ wildly
 * (e.g. CPI index points vs repo rate %). A shared axis would squash one flat;
 * two independent Y-axes (left = A, right = B) let both shapes read clearly.
 *
 * Curated macro events (from /analytics/annotations) are overlaid as vertical
 * ReferenceLines — the same pattern as RepoRateChart's 4% line, here used for
 * dated events so users can eyeball whether a kink lines up with, say, the COVID
 * lockdown or a budget.
 */

import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Annotation } from '../../api/client'
import './charts.css'

interface Row {
  date: string
  a: number
  b: number
}

interface Props {
  data: Row[]
  labelA: string
  labelB: string
  annotations: Annotation[]
}

const formatDate = (s: string) => {
  if (!s) return ''
  const d = new Date(s)
  return `${d.toLocaleString('default', { month: 'short' })} '${String(d.getFullYear()).slice(2)}`
}

const CATEGORY_COLOR: Record<Annotation['category'], string> = {
  monetary: '#4299e1',
  fiscal: '#f08c00',
  political: '#9c36b5',
}

export default function DualAxisChart({ data, labelA, labelB, annotations }: Props) {
  // Only annotate events that fall within the plotted date window, so the chart
  // isn't cluttered with reference lines that have no data behind them.
  const first = data[0]?.date ?? ''
  const last = data[data.length - 1]?.date ?? ''
  const visibleAnnotations = annotations.filter(
    a => first && last && a.date >= first && a.date <= last,
  )

  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={formatDate}
          tick={{ fontSize: 11 }}
          interval="preserveStartEnd"
        />
        <YAxis
          yAxisId="a"
          orientation="left"
          tick={{ fontSize: 11 }}
          domain={['auto', 'auto']}
          width={64}
        />
        <YAxis
          yAxisId="b"
          orientation="right"
          tick={{ fontSize: 11 }}
          domain={['auto', 'auto']}
          width={64}
        />
        <Tooltip
          labelFormatter={formatDate}
          formatter={(v: number, name: string) => [v.toLocaleString('en-IN'), name]}
        />
        <Legend />
        {visibleAnnotations.map(a => (
          <ReferenceLine
            key={a.date}
            x={a.date}
            yAxisId="a"
            stroke={CATEGORY_COLOR[a.category]}
            strokeDasharray="3 3"
            strokeOpacity={0.7}
            label={{ value: a.label, angle: -90, position: 'insideTopRight', fontSize: 9, fill: CATEGORY_COLOR[a.category] }}
          />
        ))}
        <Line
          yAxisId="a"
          type="monotone"
          dataKey="a"
          name={labelA}
          stroke="#FF9933"
          strokeWidth={2}
          dot={false}
          connectNulls
        />
        <Line
          yAxisId="b"
          type="monotone"
          dataKey="b"
          name={labelB}
          stroke="#138808"
          strokeWidth={2}
          dot={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
