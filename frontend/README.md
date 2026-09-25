# Frontend — Motor Digital Twin dashboard

React 19 + Vite + TypeScript, Tailwind CSS v4, Recharts, TanStack Query.

```bash
npm ci
npm run dev          # http://localhost:5173, proxies /api (REST + WebSocket) to VITE_BACKEND_URL or :8000
npm test             # Vitest + React Testing Library
npm run lint && npm run typecheck
npm run build        # static bundle in dist/ (served by nginx in Docker)
npx playwright test  # E2E: needs the backend on :8000 with admin/admin-pass-123 (see ../README.md)
```

Views: live dashboard (fused diagnosis, SADA panel, fault-injection console, one
panel per sensor with waveform/spectrum/scalogram/trend and a simulated↔hardware
toggle for admins) and a history view (timeline + paginated diagnoses with
filters).

Chart colors are fixed tokens in `src/index.css`: categorical slots 1–3 for
phases/axes (validated for color-vision deficiency; always with a legend) and
reserved status colors for SADA states (always with an icon + label).
