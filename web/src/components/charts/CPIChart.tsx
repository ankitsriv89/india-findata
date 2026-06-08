/**
 * CPIChart.tsx — Consumer Price Index line chart with YoY % change.
 *
 * Shows two series in one chart:
 *   - Raw CPI index value (primary Y axis, left)
 *   - YoY % change computed client-side (secondary Y axis, right)
 *
 * YoY change is computed here rather than in the API because:
 *   1. It avoids a second round-trip
 *   2. The user can switch to different CPI sub-series and the YoY
 *      recomputes instantly without a new fetch
 *
 * Base year: 2012=100
 */

import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useCPI } from '../../api/hooks'
import ChartWrapper from './ChartWrapper'
import './charts.css'

interface Props {
  from: string
  to: string
}

interface DataPoint {
  date: string
  index: number
  yoy: number | null
}

/**
 * Compute YoY % change for each data point by looking up the value
 * exactly 12 months prior.  Returns null if the prior period is absent
 * (typical for the earliest months in the range).
 */
function addYoY(data: Array<{ date: string; value: number }>): DataPoint[] {
  const byDate = new Map(data.map(d => [d.date.slice(0, 7), d.value]))

  return data.map(d => {
    const [year, month] = d.date.split('-').map(Number)
    const prevYear = year - 1
    const prevKey = `${prevYear}-${String(month).padStart(2, '0')}`
    const prevVal = byDate.get(prevKey)

    return {
      date: d.date.slice(0, 7),   // "YYYY-MM" for axis labels
      index: d.value,
      yoy: prevVal != null ? +((d.value - prevVal) / prevVal * 100).toFixed(2) : null,
    }
  })
}

const formatDate = (s: string) => {
  const [year, month] = s.split('-')
  return `${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][Number(month)-1]} ${year.slice(2)}`
}

export default function CPIChart({ from, to }: Props) {
  const { data: resp, isLoading, isError } = useCPI(from, to)
  const chartData = resp ? addYoY(resp.data) : []

  return (
    <ChartWrapper
      title="CPI — Consumer Price Index"
      subtitle={`Base year 2012=100 · ${resp?.unit ?? ''}`}
      isLoading={isLoading}
      isError={isError}
      isEmpty={chartData.length === 0}
    >
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={chartData} margin={{ top: 4, right: 40, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            tick={{ fontSize: 11 }}
            interval="preserveStartEnd"
          />
          <YAxis
            yAxisId="index"
            orientation="left"
            tick={{ fontSize: 11 }}
            domain={['auto', 'auto']}
            label={{ value: 'Index', angle: -90, position: 'insideLeft', fontSize: 10, fill: '#8892a4' }}
          />
          <YAxis
            yAxisId="yoy"
            orientation="right"
            tick={{ fontSize: 11 }}
            domain={['auto', 'auto']}
            tickFormatter={v => `${v}%`}
          />
          <Tooltip
            formatter={(value: number, name: string) =>
              name === 'YoY %' ? [`${value}%`, name] : [value.toFixed(1), name]
            }
            labelFormatter={formatDate}
          />
          <Legend />
          <Line
            yAxisId="index"
            type="monotone"
            dataKey="index"
            name="CPI Index"
            stroke="#FF9933"
            strokeWidth={2}
            dot={false}
          />
          <Bar
            yAxisId="yoy"
            dataKey="yoy"
            name="YoY %"
            fill="#4299e1"
            opacity={0.7}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartWrapper>
  )
}
