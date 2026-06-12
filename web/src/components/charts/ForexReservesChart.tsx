/**
 * ForexReservesChart.tsx — RBI foreign-exchange reserves (weekly area chart).
 *
 * Reserves move slowly week to week, so an area chart reads better than a line:
 * the filled region emphasises the *level* of the war-chest the RBI can deploy
 * to defend the rupee. USD billion on the Y axis.
 */

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useForex } from '../../api/hooks'
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

export default function ForexReservesChart({ from, to }: Props) {
  const { data: resp, isLoading, isError } = useForex(from, to)
  const chartData = resp?.data ?? []

  return (
    <ChartWrapper
      title="Forex Reserves"
      subtitle="RBI weekly total reserves · USD billion"
      isLoading={isLoading}
      isError={isError}
      isEmpty={chartData.length === 0}
    >
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={chartData} margin={{ top: 4, right: 20, left: 0, bottom: 4 }}>
          <defs>
            <linearGradient id="forexFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#138808" stopOpacity={0.4} />
              <stop offset="100%" stopColor="#138808" stopOpacity={0.03} />
            </linearGradient>
          </defs>
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
            tickFormatter={(v: number) => `$${v}`}
            width={56}
          />
          <Tooltip
            formatter={(v: number) => [`$${v.toLocaleString('en-IN')} bn`, 'Reserves']}
            labelFormatter={formatDate}
          />
          <Area
            type="monotone"
            dataKey="value"
            name="Reserves"
            stroke="#138808"
            strokeWidth={2}
            fill="url(#forexFill)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}
