/**
 * MarketsPanel.tsx — Phase 2 dashboard: equity index, FII/DII, movers, heatmap.
 *
 * Layout mirrors MacroPanel: a shared date-range picker drives the two time
 * series charts (index line + FII/DII bars), and a separate "as-of date" picker
 * drives the two cross-sectional widgets (top movers + sector heatmap), which
 * are snapshots of a single trading day rather than ranges.
 *
 * Everything renders empty-states until the bhavcopy/FII pipelines load data,
 * so the tab is fully functional the moment data flows.
 */

import { useState } from 'react'
import DateRangePicker from './DateRangePicker'
import TopMoversTable from './TopMoversTable'
import FIIDIIChart from './charts/FIIDIIChart'
import IndexChart from './charts/IndexChart'
import SectorHeatmap from './charts/SectorHeatmap'
import { today, yearsAgo } from '../api/hooks'
import './MarketsPanel.css'

export default function MarketsPanel() {
  const [from, setFrom] = useState(() => yearsAgo(1))
  const [to, setTo] = useState(() => today())
  // Cross-sectional widgets default to the latest day in range (the "to" date).
  const [asOf, setAsOf] = useState(() => today())

  return (
    <div className="markets-panel">
      <div className="markets-panel__controls">
        <h2 className="markets-panel__title">Markets Overview</h2>
        <DateRangePicker from={from} to={to} onFromChange={setFrom} onToChange={setTo} />
      </div>

      {/* Time-series charts driven by the date range */}
      <div className="markets-panel__grid">
        <div className="card">
          <IndexChart from={from} to={to} />
        </div>
        <div className="card">
          <FIIDIIChart from={from} to={to} />
        </div>
      </div>

      {/* Snapshot widgets driven by a single as-of date */}
      <div className="markets-panel__asof">
        <label className="markets-panel__asof-label">
          Snapshot date
          <input
            type="date"
            value={asOf}
            max={to}
            onChange={e => setAsOf(e.target.value)}
            className="markets-panel__asof-input"
            aria-label="Snapshot date"
          />
        </label>
      </div>

      <div className="markets-panel__grid">
        <div className="card">
          <TopMoversTable date={asOf} exchange="NSE" n={10} />
        </div>
        <div className="card">
          <SectorHeatmap date={asOf} exchange="NSE" />
        </div>
      </div>
    </div>
  )
}
