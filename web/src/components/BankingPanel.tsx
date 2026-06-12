/**
 * BankingPanel.tsx — Phase 3 dashboard: forex, M3, credit-vs-GDP, NPA.
 *
 * The 5th tab (Macro | Markets | Banking | Correlation | Pipeline). Four charts
 * in a 2×2 grid driven by a shared date-range picker, mirroring MacroPanel.
 * All charts render empty-states until the RBI DBIE pipeline loads data.
 */

import { useState } from 'react'
import DateRangePicker from './DateRangePicker'
import CreditGrowthChart from './charts/CreditGrowthChart'
import ForexReservesChart from './charts/ForexReservesChart'
import M3Chart from './charts/M3Chart'
import NPAChart from './charts/NPAChart'
import { today, yearsAgo } from '../api/hooks'
import './BankingPanel.css'

export default function BankingPanel() {
  const [from, setFrom] = useState(() => yearsAgo(5))
  const [to, setTo] = useState(() => today())

  return (
    <div className="banking-panel">
      <div className="banking-panel__controls">
        <h2 className="banking-panel__title">Banking &amp; Credit</h2>
        <DateRangePicker from={from} to={to} onFromChange={setFrom} onToChange={setTo} />
      </div>

      <div className="banking-panel__grid">
        <div className="card">
          <ForexReservesChart from={from} to={to} />
        </div>
        <div className="card">
          <M3Chart from={from} to={to} />
        </div>
        <div className="card">
          <CreditGrowthChart from={from} to={to} />
        </div>
        <div className="card">
          <NPAChart from={from} to={to} />
        </div>
      </div>
    </div>
  )
}
