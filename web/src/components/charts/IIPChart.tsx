/**
 * IIPChart.tsx — Index of Industrial Production grouped bar chart.
 *
 * Shows all four IIP sectors side-by-side per month:
 *   General | Manufacturing | Mining | Electricity
 *
 * A grouped bar makes it easy to compare sector performance for the
 * same month, and to see which sectors are driving composite IIP.
 *
 * IIP is released with a 2-month lag (April IIP released in June),
 * so the most recent 2 months will always be missing — this is normal.
 */

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useIIP } from '../../api/hooks'
import ChartWrapper from './ChartWrapper'
import './charts.css'

interface Props {
  from: string
  to: string
}

const SERIES = [
  { key: 'IIP_GENERAL',       name: 'General',       color: '#FF9933' },
  { key: 'IIP_MANUFACTURING', name: 'Manufacturing',  color: '#4299e1' },
  { key: 'IIP_MINING',        name: 'Mining',         color: '#9f7aea' },
  { key: 'IIP_ELECTRICITY',   name: 'Electricity',    color: '#138808' },
]

const fmtDate = (s: string) => {
  const [y, m] = s.split('-')
  return `${['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][Number(m)]} ${y.slice(2)}`
}

export default function IIPChart({ from, to }: Props) {
  // Fetch all four series in parallel — TanStack Query deduplicates concurrent requests
  const results = SERIES.map(s => ({
    ...s,
    // eslint-disable-next-line react-hooks/rules-of-hooks
    query: useIIP(from, to, s.key),
  }))

  const isLoading = results.some(r => r.query.isLoading)
  const isError   = results.some(r => r.query.isError)

  // Merge all series into one array keyed by date
  const byDate = new Map<string, Record<string, number>>()
  for (const { key, query } of results) {
    for (const point of query.data?.data ?? []) {
      const month = point.date.slice(0, 7)
      if (!byDate.has(month)) byDate.set(month, { date: month })
      byDate.get(month)![key] = point.value
    }
  }
  const chartData = Array.from(byDate.values()).sort((a, b) =>
    String(a.date).localeCompare(String(b.date))
  )

  return (
    <ChartWrapper
      title="IIP — Index of Industrial Production"
      subtitle="Monthly, base year 2011-12=100 · 2-month release lag"
      isLoading={isLoading}
      isError={isError}
      isEmpty={chartData.length === 0}
    >
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} margin={{ top: 4, right: 20, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={fmtDate}
            tick={{ fontSize: 10 }}
            interval={2}
          />
          <YAxis tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
          <Tooltip labelFormatter={fmtDate} />
          <Legend />
          {SERIES.map(s => (
            <Bar key={s.key} dataKey={s.key} name={s.name} fill={s.color} opacity={0.85} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}
