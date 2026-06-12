/**
 * TopMoversTable.tsx — top gainers & losers for a trading day.
 *
 * Two side-by-side lists driven by the /markets/movers endpoint, which already
 * computes %change (close vs previous close) in ClickHouse.  Gainers are green,
 * losers red; both show close price and %change.
 *
 * Empty/loading/error states are handled inline (this is a table, not a chart,
 * so it doesn't use ChartWrapper) but follows the same three-state convention.
 */

import { useMovers } from '../api/hooks'
import type { Mover } from '../api/client'
import './TopMoversTable.css'

interface Props {
  date: string
  exchange?: string
  n?: number
}

function MoverRow({ m }: { m: Mover }) {
  const up = m.change_pct >= 0
  return (
    <tr>
      <td className="movers__sym">{m.symbol}</td>
      <td className="movers__close">₹{m.close.toLocaleString('en-IN')}</td>
      <td className={up ? 'movers__pct movers__pct--up' : 'movers__pct movers__pct--down'}>
        {up ? '▲' : '▼'} {Math.abs(m.change_pct).toFixed(2)}%
      </td>
    </tr>
  )
}

function MoverList({ title, rows }: { title: string; rows: Mover[] }) {
  return (
    <div className="movers__col">
      <h4 className="movers__title">{title}</h4>
      <table className="movers__table">
        <tbody>
          {rows.map(m => (
            <MoverRow key={m.symbol} m={m} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function TopMoversTable({ date, exchange = 'NSE', n = 10 }: Props) {
  const { data, isLoading, isError } = useMovers(date, exchange, n)

  return (
    <div className="movers">
      <div className="movers__header">
        <h3 className="movers__heading">Top Movers</h3>
        <span className="movers__date">
          {exchange} · {date}
        </span>
      </div>

      {isLoading && <div className="state-loading"><span className="spinner" /> Loading…</div>}
      {!isLoading && isError && (
        <div className="state-empty">No movers for this date — pick a trading day with data</div>
      )}
      {!isLoading && !isError && data && (
        <div className="movers__grid">
          <MoverList title="Gainers" rows={data.gainers} />
          <MoverList title="Losers" rows={data.losers} />
        </div>
      )}
    </div>
  )
}
