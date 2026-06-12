/**
 * M3Chart.tsx — M3 broad money supply (monthly line chart).
 *
 * M3 is a large absolute number (lakhs of crore), so we display it in ₹ lakh
 * crore on the axis for readability. A plain monotone line suits a smooth,
 * monotonically-growing monetary aggregate.
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useM3 } from '../../api/hooks'
import ChartWrapper from './ChartWrapper'
import './charts.css'

interface Props {
  from: string
  to: string
}

const formatDate = (s: string) => {
  if (!s) return ''
  const d = new Date(s)
  return `${d.toLocaleString('default', { month: 'short' })} '${String(d.getFullYear()).slice(2)}`
}

// crore → lakh crore (÷ 100,000) for a readable axis.
const toLakhCrore = (croreValue: number) => croreValue / 1e5

export default function M3Chart({ from, to }: Props) {
  const { data: resp, isLoading, isError } = useM3(from, to)
  const chartData = (resp?.data ?? []).map(d => ({ date: d.date, value: toLakhCrore(d.value) }))

  return (
    <ChartWrapper
      title="M3 — Broad Money Supply"
      subtitle="RBI monthly M3 · ₹ lakh crore"
      isLoading={isLoading}
      isError={isError}
      isEmpty={chartData.length === 0}
    >
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={chartData} margin={{ top: 4, right: 20, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            tick={{ fontSize: 11 }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 11 }}
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => `₹${v.toFixed(0)}L`}
            width={64}
          />
          <Tooltip
            formatter={(v: number) => [`₹${v.toFixed(2)} lakh cr`, 'M3']}
            labelFormatter={formatDate}
          />
          <Line type="monotone" dataKey="value" name="M3" stroke="#4299e1" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}
