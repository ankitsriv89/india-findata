/**
 * ChartWrapper.tsx — shared loading/error/empty state shell for all charts.
 *
 * Every chart in the dashboard follows the same pattern:
 *   1. Show a spinner while the query is loading
 *   2. Show an error message if the query failed
 *   3. Show an empty state if data is empty (e.g. no data yet for this source)
 *   4. Render the chart when data is available
 *
 * This component handles 1–3 so each chart component only needs to
 * worry about the Recharts rendering logic.
 */

import type { ReactNode } from 'react'

interface Props {
  title: string
  subtitle?: string
  isLoading: boolean
  isError: boolean
  isEmpty: boolean
  children: ReactNode
}

export default function ChartWrapper({
  title,
  subtitle,
  isLoading,
  isError,
  isEmpty,
  children,
}: Props) {
  return (
    <div className="chart-wrapper">
      <div className="chart-wrapper__header">
        <div>
          <h3 className="chart-wrapper__title">{title}</h3>
          {subtitle && <p className="chart-wrapper__subtitle">{subtitle}</p>}
        </div>
      </div>

      <div className="chart-wrapper__body">
        {isLoading && (
          <div className="state-loading">
            <span className="spinner" />
            Loading…
          </div>
        )}
        {!isLoading && isError && (
          <div className="state-error">
            ⚠ Failed to load data — check pipeline status
          </div>
        )}
        {!isLoading && !isError && isEmpty && (
          <div className="state-empty">
            No data yet — run backfill to load historical data
          </div>
        )}
        {!isLoading && !isError && !isEmpty && children}
      </div>
    </div>
  )
}
