/**
 * IndexChart.tsx — benchmark index close-price line chart.
 *
 * Plots the daily close of a single benchmark instrument (default NIFTY50 on
 * NSE).  The bhavcopy sources store index/constituent closes as ordinary
 * equity Records, so this reuses the generic /markets/equity endpoint via the
 * useEquity hook — no special index endpoint needed.
 *
 * If your data doesn't yet contain a "NIFTY50" symbol (the bhavcopy is
 * constituent-level), pass any liquid symbol (e.g. RELIANCE) as a stand-in;
 * the chart shape is identical.
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
import { useEquity } from '../../api/hooks'
import ChartWrapper from './ChartWrapper'
import './charts.css'

interface Props {
  from: string
  to: string
  symbol?: string
  exchange?: string
}

const formatDate = (s: string) => {
  if (!s) return ''
  const d = new Date(s)
  return `${d.toLocaleString('default', { month: 'short' })} '${String(d.getFullYear()).slice(2)}`
}

export default function IndexChart({ from, to, symbol = 'NIFTY50', exchange = 'NSE' }: Props) {
  const { data: resp, isLoading, isError } = useEquity(symbol, from, to, exchange, 'close_price')
  const chartData = resp?.data ?? []

  return (
    <ChartWrapper
      title={`${symbol} — Close`}
      subtitle={`${exchange} daily close · ₹`}
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
            tickFormatter={(v: number) => v.toLocaleString('en-IN')}
            width={64}
          />
          <Tooltip
            formatter={(v: number) => [`₹${v.toLocaleString('en-IN')}`, 'Close']}
            labelFormatter={formatDate}
          />
          <Line
            type="monotone"
            dataKey="value"
            name="Close"
            stroke="#FF9933"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}
