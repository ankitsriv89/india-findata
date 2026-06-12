/**
 * CreditGrowthChart.tsx — bank credit growth vs GDP growth (overlay).
 *
 * The credit–growth relationship is one of the most-watched in macro-finance:
 * credit growth running well ahead of GDP growth can signal over-leverage;
 * lagging it can signal a credit crunch. We overlay both as lines on a shared
 * percent axis. Credit is monthly; GDP is quarterly — Recharts aligns them by
 * the shared `date` key and simply leaves gaps where one series has no point.
 *
 * Reuses the Phase 1 `useGDP` hook — a small example of the cross-domain reuse
 * the platform is built for (one `records` table, many layers querying it).
 */

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useCredit, useGDP } from '../../api/hooks'
import ChartWrapper from './ChartWrapper'
import './charts.css'

interface Props {
  from: string
  to: string
}

interface Row {
  date: string
  credit?: number
  gdp?: number
}

const formatDate = (s: string) => {
  if (!s) return ''
  const d = new Date(s)
  return `${d.toLocaleString('default', { month: 'short' })} '${String(d.getFullYear()).slice(2)}`
}

/** Merge credit (monthly) and GDP (quarterly) series by date. */
function merge(
  credit: Array<{ date: string; value: number }>,
  gdp: Array<{ date: string; value: number }>,
): Row[] {
  const map = new Map<string, Row>()
  for (const r of credit) map.set(r.date, { date: r.date, credit: r.value })
  for (const r of gdp) {
    const existing = map.get(r.date) ?? { date: r.date }
    map.set(r.date, { ...existing, gdp: r.value })
  }
  return Array.from(map.values()).sort((a, b) => a.date.localeCompare(b.date))
}

export default function CreditGrowthChart({ from, to }: Props) {
  const { data: creditResp, isLoading: l1, isError: e1 } = useCredit(from, to)
  const { data: gdpResp, isLoading: l2 } = useGDP(from, to)

  // GDP is a nice-to-have overlay; don't fail the whole chart if only GDP errors
  // (we deliberately ignore the GDP error flag here).
  const isLoading = l1 || l2
  const isError = e1
  const data = merge(creditResp?.data ?? [], gdpResp?.data ?? [])

  return (
    <ChartWrapper
      title="Bank Credit Growth vs GDP"
      subtitle="Credit growth (monthly) & GDP growth (quarterly) · % YoY"
      isLoading={isLoading}
      isError={isError}
      isEmpty={data.length === 0}
    >
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 4, right: 20, left: 0, bottom: 4 }}>
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
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            formatter={(v: number, name: string) => [`${v}%`, name]}
            labelFormatter={formatDate}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="credit"
            name="Credit growth"
            stroke="#FF9933"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="gdp"
            name="GDP growth"
            stroke="#4299e1"
            strokeWidth={2}
            strokeDasharray="5 3"
            dot={{ r: 3, fill: '#4299e1' }}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}
