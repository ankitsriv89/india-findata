/**
 * MacroPanel.tsx — Phase 1 dashboard: CPI, Repo Rate, GDP, IIP.
 *
 * Four charts arranged in a 2×2 grid on wide viewports, stacked on mobile.
 * Each chart fetches its own data via TanStack Query hooks.
 *
 * Date range is controlled by a shared picker at the top of the panel.
 * Default: last 5 years.
 */

import { useState } from 'react'
import CPIChart from './charts/CPIChart'
import RepoRateChart from './charts/RepoRateChart'
import GDPChart from './charts/GDPChart'
import IIPChart from './charts/IIPChart'
import DateRangePicker from './DateRangePicker'
import { yearsAgo, today } from '../api/hooks'
import './MacroPanel.css'

export default function MacroPanel() {
  const [from, setFrom] = useState(() => yearsAgo(5))
  const [to, setTo] = useState(() => today())

  return (
    <div className="macro-panel">
      <div className="macro-panel__controls">
        <h2 className="macro-panel__title">Macro Overview</h2>
        <DateRangePicker from={from} to={to} onFromChange={setFrom} onToChange={setTo} />
      </div>

      <div className="macro-panel__grid">
        <div className="card">
          <CPIChart from={from} to={to} />
        </div>
        <div className="card">
          <RepoRateChart from={from} to={to} />
        </div>
        <div className="card">
          <GDPChart from={from} to={to} />
        </div>
        <div className="card">
          <IIPChart from={from} to={to} />
        </div>
      </div>
    </div>
  )
}
