/**
 * api/hooks.ts — TanStack Query hooks for all API endpoints.
 *
 * Each hook wraps one API endpoint with sensible staleTime and error handling.
 * Components import these hooks directly — never call apiClient from components.
 *
 * staleTime philosophy:
 *   Macro data (CPI, IIP, GDP, rates) — 5 minutes.
 *     These update monthly/quarterly, no need to refetch on every focus.
 *   Pipeline status — 30 seconds.
 *     Jobs can complete between page focuses; short poll gives live feedback.
 */

import { useQuery } from '@tanstack/react-query'
import {
  apiClient,
  TimeSeriesResponse,
  PipelineRun,
  MoversResponse,
  HeatmapResponse,
} from './client'

// ── Date range helpers ────────────────────────────────────────────────────────

/** Format a Date as "YYYY-MM-DD" for API query params */
function fmt(d: Date): string {
  return d.toISOString().slice(0, 10)
}

/** today's date string */
export function today(): string {
  return fmt(new Date())
}

/** Date string N years before today */
export function yearsAgo(n: number): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - n)
  return fmt(d)
}

// ── Macro hooks ───────────────────────────────────────────────────────────────

export function useCPI(from: string, to: string, series = 'CPI_GENERAL') {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['macro', 'cpi', series, from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/macro/cpi', {
        params: { series, from, to },
      })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}

export function useIIP(from: string, to: string, series = 'IIP_GENERAL') {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['macro', 'iip', series, from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/macro/iip', {
        params: { series, from, to },
      })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}

export function useGDP(from: string, to: string) {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['macro', 'gdp', from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/macro/gdp', {
        params: { from, to },
      })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}

export function useRates(from: string, to: string, series = 'REPO_RATE') {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['macro', 'rates', series, from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/macro/rates', {
        params: { series, from, to },
      })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}

// ── Markets hooks (Phase 2) ─────────────────────────────────────────────────────

/**
 * Daily price (or volume) series for one equity symbol.
 * Used for the index line chart (NIFTY50 close) and any per-symbol chart.
 */
export function useEquity(
  symbol: string,
  from: string,
  to: string,
  exchange = 'NSE',
  dimension = 'close_price',
) {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['markets', 'equity', exchange, symbol, dimension, from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/markets/equity', {
        params: { symbol, exchange, dimension, from, to },
      })
      return data
    },
    // Equity EOD updates once/day — 5 min stale is fine.
    staleTime: 5 * 60 * 1000,
    // Don't fire until a symbol is chosen.
    enabled: symbol.length > 0,
  })
}

/** Daily FII/DII net equity flow series (crore INR; negative = net selling). */
export function useFIIDII(from: string, to: string, series = 'FII_NET_EQUITY') {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['markets', 'fii', series, from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/markets/fii', {
        params: { series, from, to },
      })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}

/** Top gainers/losers for an exchange on a given date. */
export function useMovers(date: string, exchange = 'NSE', n = 10) {
  return useQuery<MoversResponse>({
    queryKey: ['markets', 'movers', exchange, date, n],
    queryFn: async () => {
      const { data } = await apiClient.get('/markets/movers', {
        params: { date, exchange, n },
      })
      return data
    },
    staleTime: 5 * 60 * 1000,
    enabled: date.length > 0,
  })
}

/** Sector heatmap (average %change per sector) for an exchange on a given date. */
export function useHeatmap(date: string, exchange = 'NSE') {
  return useQuery<HeatmapResponse>({
    queryKey: ['markets', 'heatmap', exchange, date],
    queryFn: async () => {
      const { data } = await apiClient.get('/markets/heatmap', {
        params: { date, exchange },
      })
      return data
    },
    staleTime: 5 * 60 * 1000,
    enabled: date.length > 0,
  })
}

// ── Banking hooks (Phase 3) ──────────────────────────────────────────────────

/** Forex reserves — weekly, USD billion. */
export function useForex(from: string, to: string) {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['banking', 'forex', from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/banking/forex', { params: { from, to } })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}

/** M3 broad money supply — monthly, crore INR. */
export function useM3(from: string, to: string) {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['banking', 'm3', from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/banking/m3', { params: { from, to } })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}

/** Bank credit growth — monthly, percent (YoY). */
export function useCredit(from: string, to: string) {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['banking', 'credit', from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/banking/credit', { params: { from, to } })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}

/** Gross NPA ratio — quarterly, percent. */
export function useNPA(from: string, to: string) {
  return useQuery<TimeSeriesResponse>({
    queryKey: ['banking', 'npa', from, to],
    queryFn: async () => {
      const { data } = await apiClient.get('/banking/npa', { params: { from, to } })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}

// ── Pipeline hooks ────────────────────────────────────────────────────────────

export function usePipelineStatus() {
  return useQuery<PipelineRun[]>({
    queryKey: ['pipeline', 'status'],
    queryFn: async () => {
      const { data } = await apiClient.get('/pipeline/status')
      return data
    },
    // Poll every 30 seconds to catch job completions in real time
    refetchInterval: 30 * 1000,
    staleTime: 15 * 1000,
  })
}

export function usePipelineRuns(
  source?: string,
  status?: string,
  limit = 50,
) {
  return useQuery<PipelineRun[]>({
    queryKey: ['pipeline', 'runs', source, status, limit],
    queryFn: async () => {
      const { data } = await apiClient.get('/pipeline/runs', {
        params: { source, status, limit },
      })
      return data
    },
    staleTime: 15 * 1000,
  })
}
