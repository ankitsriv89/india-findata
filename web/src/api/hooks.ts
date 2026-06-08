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
import { apiClient, TimeSeriesResponse, PipelineRun } from './client'

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
