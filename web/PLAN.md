# web/ — React + Vite Dashboard

## Overview

TypeScript SPA. Four tabs: Macro | Markets | Correlation | Pipeline.
All data from the FastAPI at `VITE_API_URL` (default `http://localhost:8090`).
No mock data — components render a loading state while fetching, error state on failure.

---

## Tech choices

- **React 18** + TypeScript, hooks only (no class components)
- **Recharts** — line, bar, area charts for time series (simpler API than D3 for standard charts)
- **D3.js** — sector heatmap (custom colour scale + grid layout)
- **TanStack Query** — data fetching, caching, background refresh (avoids manual useEffect chains)
- **date-fns** — date formatting (lightweight, tree-shakeable)
- No CSS framework — plain CSS with CSS custom properties for theming

---

## Component tree

```
App.tsx
└── Layout.tsx (tab bar)
    ├── MacroPanel.tsx
    │   ├── CPIChart.tsx         — recharts LineChart, CPI index YoY
    │   ├── RepoRateChart.tsx    — recharts StepChart (rates change discretely)
    │   ├── GDPChart.tsx         — recharts BarChart, quarterly growth %
    │   └── IIPChart.tsx         — recharts BarChart, IIP by sector
    │
    ├── MarketsPanel.tsx
    │   ├── IndexChart.tsx       — recharts LineChart, NIFTY50 EOD close
    │   ├── FIIDIIChart.tsx      — recharts BarChart, net FII/DII daily flows
    │   ├── TopMoversTable.tsx   — top 10 gainers/losers by % change
    │   └── SectorHeatmap.tsx    — D3 grid, % change by NSE sector
    │
    ├── CorrelationPanel.tsx
    │   ├── SeriesSelector.tsx   — two dropdowns: pick any two series
    │   ├── DualAxisChart.tsx    — recharts ComposedChart, dual Y axes
    │   └── CorrCoeff.tsx        — Pearson r computed client-side, displayed as badge
    │
    └── PipelinePanel.tsx
        ├── SourceStatusTable.tsx — last run, rows inserted, next run, status badge
        └── RunHistoryTable.tsx  — paginated recent runs with error message on expand
```

---

## API hooks (TanStack Query)

```typescript
// src/hooks/useRecords.ts
export function useCPI(from: string, to: string) {
  return useQuery({
    queryKey: ['macro', 'cpi', from, to],
    queryFn: () => api.get('/macro/cpi', { params: { from, to } }),
    staleTime: 5 * 60 * 1000,  // 5 minutes — macro data doesn't change mid-day
  })
}

export function useNIFTY50(from: string, to: string) {
  return useQuery({
    queryKey: ['markets', 'nifty50', from, to],
    queryFn: () => api.get('/markets/indices', { params: { index: 'NIFTY50', from, to } }),
    staleTime: 60 * 1000,  // 1 minute — market data refreshes once daily but poll more often
  })
}

export function usePipelineStatus() {
  return useQuery({
    queryKey: ['pipeline', 'status'],
    queryFn: () => api.get('/pipeline/status'),
    refetchInterval: 30 * 1000,  // poll every 30s to catch job completions
  })
}
```

---

## Correlation panel — client-side Pearson r

```typescript
// compute Pearson correlation between two aligned date series
function pearsonR(xs: number[], ys: number[]): number {
  const n = xs.length
  const meanX = xs.reduce((a, b) => a + b, 0) / n
  const meanY = ys.reduce((a, b) => a + b, 0) / n
  const num = xs.reduce((sum, x, i) => sum + (x - meanX) * (ys[i] - meanY), 0)
  const den = Math.sqrt(
    xs.reduce((s, x) => s + (x - meanX) ** 2, 0) *
    ys.reduce((s, y) => s + (y - meanY) ** 2, 0)
  )
  return den === 0 ? 0 : num / den
}
```

Date alignment: join both series on `date` field before computing (inner join semantics —
only dates present in both series contribute).

---

## Date range controls

Global date range picker (shared across all tabs):
- Presets: 1M | 3M | 6M | 1Y | 3Y | 5Y
- Custom: start/end date inputs
- Stored in URL query params (`?from=2023-01-01&to=2026-06-02`) so links are shareable

---

## Layout

Three-panel preferred on wide viewports:
- Left 280px: controls (date range, series selector, filters)
- Centre: main chart (full height)
- Right 320px: secondary data (top movers, correlation badge, run status)

Collapses to single column on < 768px viewport.

Dark background (`#0f1117`) with accent colours matching Indian flag palette:
- Primary: `#FF9933` (saffron) for upward/positive
- Secondary: `#138808` (green) for neutral/growth
- Alert: `#e53e3e` for negative/errors
- Text: `#e2e8f0`

---

## Vite config

```typescript
// vite.config.ts
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5190,
    proxy: {
      '/macro': 'http://localhost:8090',
      '/markets': 'http://localhost:8090',
      '/pipeline': 'http://localhost:8090',
    }
  }
})
```

Proxy avoids CORS during development — requests to `/macro/...` are forwarded to FastAPI.

---

## Build + Docker

```dockerfile
# Final stage: serve with nginx
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
```

Production build output goes to `web/dist/` (gitignored). The Docker image serves the
built SPA via nginx. FastAPI serves the data API — they are separate containers.
