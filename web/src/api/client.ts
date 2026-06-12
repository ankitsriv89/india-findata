/**
 * api/client.ts — axios instance pre-configured for the FastAPI backend.
 *
 * The base URL comes from the VITE_API_URL environment variable (set in
 * .env or docker-compose).  In development the Vite proxy forwards /macro,
 * /markets, /pipeline to localhost:8090 so VITE_API_URL can be empty.
 *
 * All API responses follow the same envelope:
 *   { series, from_date, to_date, granularity, unit, data: [{date, value}] }
 */

import axios from 'axios'

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '',
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

/** Standard time-series response from /macro/* endpoints */
export interface TimeSeriesResponse {
  series: string
  from_date: string
  to_date: string
  granularity: string
  unit: string
  data: Array<{ date: string; value: number }>
}

/** One symbol's day move (from /markets/movers) */
export interface Mover {
  symbol: string
  close: number
  prev_close: number
  change_pct: number
}

/** Top gainers/losers snapshot from /markets/movers */
export interface MoversResponse {
  exchange: string
  date: string
  gainers: Mover[]
  losers: Mover[]
}

/** One sector cell from /markets/heatmap */
export interface HeatmapCell {
  sector: string
  change_pct: number
  symbols: number
}

/** Sector heatmap grid from /markets/heatmap */
export interface HeatmapResponse {
  exchange: string
  date: string
  cells: HeatmapCell[]
}

/** One pipeline run row */
export interface PipelineRun {
  source: string
  job_id: string | null
  started_at: string
  finished_at: string | null
  rows_fetched: number
  rows_inserted: number
  status: 'running' | 'success' | 'failed'
  error_msg: string | null
}
