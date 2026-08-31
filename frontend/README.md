# SentinelLLM — Web Dashboard

Frontend for SentinelLLM, an LLM reliability / evaluation / observability
platform. Built with Next.js 14 (App Router), TypeScript (strict), Tailwind
CSS, and Recharts. Talks to a separately-built FastAPI backend over a typed
REST client — the UI degrades gracefully (loading/empty/error states) when
that backend is unreachable, including at build time.

## Requirements

- Node.js 20+
- The SentinelLLM backend (optional for `npm run build`/`npm run dev` to
  start, required to see real data)

## Getting started

```bash
npm install
cp .env.example .env.local   # then edit as needed
npm run dev
```

The app runs at `http://localhost:3000`.

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the FastAPI backend |
| `NEXT_PUBLIC_API_KEY` | `demo-api-key` | Sent as the `X-API-Key` header on every request |

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start the dev server |
| `npm run build` | Production build (standalone output, type-checked) |
| `npm run start` | Run the production build |
| `npm run lint` | ESLint (`next lint`) |
| `npm test` | Jest + React Testing Library unit tests |

## Project layout

```
app/                 App Router pages (one folder per route)
  overview/           KPIs, time series, model/provider breakdowns
  traces/              filterable/paginated trace table
  trace/[id]/          trace detail: spans, I/O, evaluation, routing, raw JSON
  evaluations/         evaluation runs + pass-rate-by-metric
  datasets/[id]/        dataset list + sample record viewer
  experiments/         experiment list + 2-way comparison chart
  prompts/              prompt registry (versions, status, template viewer)
  models/               model registry + quality-vs-cost scatter
  routing/               routing decision log + model-selection breakdown
  regressions/          detected regressions, sorted by severity
  cost/                 cost totals, daily trend, breakdown by model/app
  settings/              alert rules (live) + API-key/webhook placeholders
components/           Sidebar, Topbar, MetricCard, StatusBadge, DataTable,
                      TimelineChart, JsonViewer, ScoreBar, FilterBar, Panel,
                      StateViews (loading/empty/error)
lib/                  api.ts (typed fetch client), types.ts (API contract),
                      format.ts, useFetch.ts, filters-context.tsx
__tests__/            Jest + React Testing Library specs
```

## Design notes

- All data-bearing pages are client components (`"use client"`) that fetch
  in `useEffect` via `lib/useFetch.ts`, so `npm run build` never depends on
  the backend being reachable.
- Every list/detail view renders three states explicitly: loading
  (skeletons), error (with retry), and empty — never fabricated data.
- The dark, data-dense visual style intentionally mirrors developer
  observability tools (Datadog/Honeycomb/Grafana) rather than a marketing
  site; numeric/ID values use a monospace font throughout.
- Small field-name or shape mismatches against the real backend are
  expected and should be reconciled in `lib/types.ts` / `lib/api.ts`.

## Docker

```bash
docker build -t sentinellm-frontend .
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_API_URL=http://backend:8000 \
  -e NEXT_PUBLIC_API_KEY=demo-api-key \
  sentinellm-frontend
```

The image uses Next.js's `output: "standalone"` build for a minimal
production runtime.
