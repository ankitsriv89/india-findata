/**
 * RepoRateChart.tsx — RBI repo rate step chart.
 *
 * Rates change discretely on MPC meeting dates (~6 times/year), so we
 * render a step line (type="stepAfter") rather than a smooth curve.
 * A smooth curve would imply gradual changes between meetings, which is
 * misleading — the rate is constant until the next MPC decision.
 *
 * Also plots reverse repo rate as a secondary step line.
 */

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { useRates } from '../../api/hooks'
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

export default function RepoRateChart({ from, to }: Props) {
  const { data: repoResp, isLoading: l1, isError: e1 } = useRates(from, to, 'REPO_RATE')
  const { data: rrResp,   isLoading: l2, isError: e2 } = useRates(from, to, 'REVERSE_REPO_RATE')

  const isLoading = l1 || l2
  const isError = e1 || e2

  // Merge both series by date into one chart data array
  const merged = mergeRateSeries(
    repoResp?.data ?? [],
    rrResp?.data ?? [],
  )

  return (
    <ChartWrapper
      title="RBI Policy Rates"
      subtitle="Repo rate & reverse repo — changes on MPC meeting dates"
      isLoading={isLoading}
      isError={isError}
      isEmpty={merged.length === 0}
    >
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={merged} margin={{ top: 4, right: 20, left: 0, bottom: 4 }}>
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
            tickFormatter={v => `${v}%`}
          />
          <Tooltip
            formatter={(v: number) => [`${v}%`]}
            labelFormatter={formatDate}
          />
          <Legend />
          {/* 4% reference line — helps visualise RBI's inflation target midpoint */}
          <ReferenceLine y={4} stroke="#8892a4" strokeDasharray="4 4" label={{ value: '4%', fill: '#8892a4', fontSize: 10 }} />
          <Line
            type="stepAfter"
            dataKey="repo"
            name="Repo Rate"
            stroke="#FF9933"
            strokeWidth={2.5}
            dot={{ r: 3, fill: '#FF9933' }}
          />
          <Line
            type="stepAfter"
            dataKey="reverseRepo"
            name="Reverse Repo"
            stroke="#4299e1"
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="5 3"
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}

function mergeRateSeries(
  repo: Array<{ date: string; value: number }>,
  reverseRepo: Array<{ date: string; value: number }>,
): Array<{ date: string; repo?: number; reverseRepo?: number }> {
  const map = new Map<string, { date: string; repo?: number; reverseRepo?: number }>()

  for (const r of repo) {
    map.set(r.date, { date: r.date, repo: r.value })
  }
  for (const r of reverseRepo) {
    const existing = map.get(r.date) ?? { date: r.date }
    map.set(r.date, { ...existing, reverseRepo: r.value })
  }

  return Array.from(map.values()).sort((a, b) => a.date.localeCompare(b.date))
}
