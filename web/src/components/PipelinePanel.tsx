/**
 * PipelinePanel.tsx — pipeline status and run history dashboard tab.
 *
 * Two tables:
 *   1. Source Status — one row per source, latest run result
 *   2. Run History   — paginated recent runs, expandable error messages
 */

import { useState } from 'react'
import { usePipelineStatus, usePipelineRuns } from '../api/hooks'
import type { PipelineRun } from '../api/client'
import './PipelinePanel.css'

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge--${status}`}>{status}</span>
}

function fmtTime(s: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

function duration(start: string, end: string | null): string {
  if (!end) return 'running…'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

export default function PipelinePanel() {
  const { data: statusRows, isLoading: sl, isError: se } = usePipelineStatus()
  const { data: historyRows, isLoading: hl, isError: he } = usePipelineRuns()
  const [expandedId, setExpandedId] = useState<string | null>(null)

  return (
    <div className="pipeline-panel">

      {/* ── Source Status Table ─────────────────────────── */}
      <section className="card pipeline-panel__section">
        <h3 className="pipeline-panel__section-title">Source Status</h3>
        {sl && <div className="state-loading"><span className="spinner" /> Loading…</div>}
        {se && <div className="state-error">⚠ Failed to load pipeline status</div>}
        {!sl && !se && (
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>Last Run</th>
                <th>Duration</th>
                <th>Rows Inserted</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(statusRows ?? []).length === 0 && (
                <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>
                  No runs yet — start the app and wait for the first scheduled job,
                  or run <code>python -m scripts.backfill --all --from 2020-01-01</code>
                </td></tr>
              )}
              {(statusRows ?? []).map((row: PipelineRun) => (
                <tr key={row.source}>
                  <td><code>{row.source}</code></td>
                  <td>{fmtTime(row.started_at)}</td>
                  <td>{duration(row.started_at, row.finished_at)}</td>
                  <td>{row.rows_inserted.toLocaleString()}</td>
                  <td><StatusBadge status={row.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* ── Run History Table ───────────────────────────── */}
      <section className="card pipeline-panel__section">
        <h3 className="pipeline-panel__section-title">Recent Runs</h3>
        {hl && <div className="state-loading"><span className="spinner" /> Loading…</div>}
        {he && <div className="state-error">⚠ Failed to load run history</div>}
        {!hl && !he && (
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Fetched</th>
                <th>Inserted</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(historyRows ?? []).map((row: PipelineRun, i: number) => {
                const rowKey = `${row.source}-${row.started_at}`
                const isExpanded = expandedId === rowKey
                return [
                  <tr
                    key={rowKey}
                    onClick={() => row.error_msg ? setExpandedId(isExpanded ? null : rowKey) : undefined}
                    style={{ cursor: row.error_msg ? 'pointer' : 'default' }}
                  >
                    <td><code>{row.source}</code></td>
                    <td>{fmtTime(row.started_at)}</td>
                    <td>{duration(row.started_at, row.finished_at)}</td>
                    <td>{row.rows_fetched.toLocaleString()}</td>
                    <td>{row.rows_inserted.toLocaleString()}</td>
                    <td><StatusBadge status={row.status} /></td>
                  </tr>,
                  isExpanded && row.error_msg && (
                    <tr key={`${rowKey}-err`} className="pipeline-panel__error-row">
                      <td colSpan={6}>
                        <pre className="pipeline-panel__error">{row.error_msg}</pre>
                      </td>
                    </tr>
                  ),
                ]
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
