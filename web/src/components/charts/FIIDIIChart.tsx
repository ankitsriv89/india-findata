/**
 * FIIDIIChart.tsx — FII vs DII daily net equity flows.
 *
 * Institutional flows are the clearest sentiment signal in Indian markets:
 *   - FII (foreign) net flow — bars, can be negative (net selling)
 *   - DII (domestic) net flow — bars, often counter to FII
 *
 * Both are plotted as grouped bars on a single crore-INR axis.  A zero
 * reference line separates net buying (above) from net selling (below).
 *
 * Mirrors CPIChart's two-query + client-side merge pattern: we fetch the FII
 * and DII series independently and merge them by date.
 */

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useFIIDII } from '../../api/hooks'
import ChartWrapper from './ChartWrapper'
import './charts.css'

interface Props {
  from: string
  to: string
}

interface Row {
  date: string
  fii?: number
  dii?: number
}

const formatDate = (s: string) => {
  if (!s) return ''
  const d = new Date(s)
  return `${d.toLocaleString('default', { month: 'short' })} '${String(d.getFullYear()).slice(2)}`
}

/** Merge the FII and DII series into one row per date. */
function merge(
  fii: Array<{ date: string; value: number }>,
  dii: Array<{ date: string; value: number }>,
): Row[] {
  const map = new Map<string, Row>()
  for (const r of fii) map.set(r.date, { date: r.date, fii: r.value })
  for (const r of dii) {
    const existing = map.get(r.date) ?? { date: r.date }
    map.set(r.date, { ...existing, dii: r.value })
  }
  return Array.from(map.values()).sort((a, b) => a.date.localeCompare(b.date))
}

export default function FIIDIIChart({ from, to }: Props) {
  const { data: fiiResp, isLoading: l1, isError: e1 } = useFIIDII(from, to, 'FII_NET_EQUITY')
  const { data: diiResp, isLoading: l2, isError: e2 } = useFIIDII(from, to, 'DII_NET_EQUITY')

  const isLoading = l1 || l2
  const isError = e1 || e2
  const data = merge(fiiResp?.data ?? [], diiResp?.data ?? [])

  return (
    <ChartWrapper
      title="FII / DII Net Equity Flows"
      subtitle="Daily institutional net buying (+) / selling (−) · ₹ crore"
      isLoading={isLoading}
      isError={isError}
      isEmpty={data.length === 0}
    >
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 4, right: 20, left: 0, bottom: 4 }}>
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
            formatter={(v: number, name: string) => [`₹${v.toLocaleString('en-IN')} cr`, name]}
            labelFormatter={formatDate}
          />
          <Legend />
          <ReferenceLine y={0} stroke="#8892a4" />
          <Bar dataKey="fii" name="FII" fill="#FF9933" opacity={0.85} />
          <Bar dataKey="dii" name="DII" fill="#4299e1" opacity={0.85} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}
