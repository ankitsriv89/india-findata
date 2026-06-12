/**
 * NPAChart.tsx — gross NPA ratio (quarterly bar chart).
 *
 * The gross non-performing-asset ratio is the headline bank-health metric. Bars
 * (one per quarter) read better than a line for a sparse quarterly series, and
 * the colour shifts toward red as the ratio rises — a quick visual stress gauge.
 * A 5% reference line marks a commonly-cited concern threshold.
 */

import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useNPA } from '../../api/hooks'
import ChartWrapper from './ChartWrapper'
import './charts.css'

interface Props {
  from: string
  to: string
}

const formatQuarter = (s: string) => {
  if (!s) return ''
  const [year, month] = s.split('-').map(Number)
  // Indian fiscal: Apr=Q1, Jul=Q2, Oct=Q3, Jan=Q4.
  const q = { 4: 'Q1', 7: 'Q2', 10: 'Q3', 1: 'Q4' }[month] ?? ''
  return `${q} '${String(year).slice(2)}`
}

// Green (healthy) → red (stressed) as the ratio climbs past ~4%.
const barColor = (v: number) => (v >= 5 ? '#e03131' : v >= 4 ? '#f08c00' : '#138808')

export default function NPAChart({ from, to }: Props) {
  const { data: resp, isLoading, isError } = useNPA(from, to)
  const chartData = resp?.data ?? []

  return (
    <ChartWrapper
      title="Gross NPA Ratio"
      subtitle="Scheduled commercial banks · quarterly · %"
      isLoading={isLoading}
      isError={isError}
      isEmpty={chartData.length === 0}
    >
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} margin={{ top: 4, right: 20, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatQuarter}
            tick={{ fontSize: 11 }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 11 }}
            domain={[0, 'auto']}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            formatter={(v: number) => [`${v}%`, 'Gross NPA']}
            labelFormatter={formatQuarter}
          />
          <ReferenceLine y={5} stroke="#e03131" strokeDasharray="4 4" label={{ value: '5%', fill: '#e03131', fontSize: 10 }} />
          <Bar dataKey="value" name="Gross NPA">
            {chartData.map((d, i) => (
              <Cell key={i} fill={barColor(d.value)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}
