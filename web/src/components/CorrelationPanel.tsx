/**
 * CorrelationPanel.tsx — Phase 4 cross-domain correlation explorer.
 *
 * Pick any two series from the macro/markets/banking layers and the panel pulls
 * both, aligns them by date in the API, and shows:
 *   - a dual-axis chart of the two aligned series (with macro-event annotations)
 *   - a Pearson r badge with a plain-language strength + best-lag hint
 *
 * This is the payoff of the universal Record schema: any series correlates with
 * any other through one endpoint, no per-pair plumbing.
 */

import { useState } from 'react'
import DateRangePicker from './DateRangePicker'
import SeriesSelector, { SERIES_CATALOGUE, SeriesOption } from './SeriesSelector'
import CorrCoeff from './CorrCoeff'
import DualAxisChart from './charts/DualAxisChart'
import { useAnnotations, useCorrelation, today, yearsAgo } from '../api/hooks'
import './CorrelationPanel.css'

export default function CorrelationPanel() {
  const [from, setFrom] = useState(() => yearsAgo(5))
  const [to, setTo] = useState(() => today())
  // Defaults: a classic pairing — inflation vs the policy rate.
  const [a, setA] = useState<SeriesOption>(SERIES_CATALOGUE[0])      // CPI_GENERAL
  const [b, setB] = useState<SeriesOption>(SERIES_CATALOGUE[4])      // REPO_RATE

  const { data, isLoading, isError } = useCorrelation(
    a.source, a.series, b.source, b.series, from, to,
  )
  const { data: annotations } = useAnnotations()

  return (
    <div className="corr-panel">
      <div className="corr-panel__controls">
        <h2 className="corr-panel__title">Correlation Explorer</h2>
        <DateRangePicker from={from} to={to} onFromChange={setFrom} onToChange={setTo} />
      </div>

      <div className="corr-panel__selectors">
        <SeriesSelector id="series-a" label="Series A (left axis)" value={a} onChange={setA} />
        <span className="corr-panel__vs">vs</span>
        <SeriesSelector id="series-b" label="Series B (right axis)" value={b} onChange={setB} />
      </div>

      <div className="card corr-panel__chart">
        {isLoading && <div className="state-loading"><span className="spinner" /> Loading…</div>}
        {!isLoading && isError && (
          <div className="state-empty">
            One of these series has no data yet — load it via backfill, or pick another pair
          </div>
        )}
        {!isLoading && !isError && data && (
          <>
            <CorrCoeff
              r={data.pearson_r}
              n={data.n}
              bestLag={data.best_lag}
              bestLagR={data.best_lag_r}
            />
            <DualAxisChart
              data={data.data}
              labelA={a.label}
              labelB={b.label}
              annotations={annotations ?? []}
            />
          </>
        )}
      </div>
    </div>
  )
}
