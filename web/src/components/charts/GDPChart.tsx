/**
 * GDPChart.tsx — quarterly GDP growth rate bar chart.
 *
 * Bars are coloured by sign: saffron for positive growth, red for negative.
 * India has rarely had negative GDP growth (COVID quarter is a notable exception —
 * Q1 FY21 showed -24.4% which this chart correctly renders in red).
 *
 * X-axis labels use the fiscal quarter format: "Q1 FY24" etc.
 */

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Cell,
  ResponsiveContainer,
} from 'recharts'
import { useGDP } from '../../api/hooks'
import ChartWrapper from './ChartWrapper'
import './charts.css'

interface Props {
  from: string
  to: string
}

// Format "YYYY-MM-DD" → "Q1 FY24" using India's fiscal year (Apr start)
function toFiscalLabel(dateStr: string): string {
  const d = new Date(dateStr)
  const month = d.getMonth() + 1 // 1–12
  const year = d.getFullYear()

  // Fiscal year starts April 1.
  // Apr–Jun = Q1, Jul–Sep = Q2, Oct–Dec = Q3, Jan–Mar = Q4
  if (month >= 4 && month <= 6)  return `Q1 FY${String(year + 1).slice(2)}`
  if (month >= 7 && month <= 9)  return `Q2 FY${String(year + 1).slice(2)}`
  if (month >= 10 && month <= 12) return `Q3 FY${String(year + 1).slice(2)}`
  return `Q4 FY${String(year).slice(2)}`
}

export default function GDPChart({ from, to }: Props) {
  const { data: resp, isLoading, isError } = useGDP(from, to)

  const chartData = (resp?.data ?? []).map(d => ({
    label: toFiscalLabel(d.date),
    value: d.value,
  }))

  return (
    <ChartWrapper
      title="GDP Growth Rate (YoY %)"
      subtitle="Quarterly, at constant prices (base 2011-12)"
      isLoading={isLoading}
      isError={isError}
      isEmpty={chartData.length === 0}
    >
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} margin={{ top: 4, right: 20, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={1} />
          <YAxis
            tick={{ fontSize: 11 }}
            tickFormatter={v => `${v}%`}
            domain={['auto', 'auto']}
          />
          <Tooltip formatter={(v: number) => [`${v.toFixed(1)}%`, 'YoY Growth']} />
          {/* Zero line — makes it obvious when growth turns negative */}
          <ReferenceLine y={0} stroke="#8892a4" />
          <Bar dataKey="value" name="GDP Growth %">
            {chartData.map((d, i) => (
              <Cell
                key={i}
                fill={d.value >= 0 ? '#FF9933' : '#e53e3e'}
                opacity={0.85}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}
