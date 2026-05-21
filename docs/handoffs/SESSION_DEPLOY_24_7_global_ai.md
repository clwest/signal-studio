# SESSION — Joined the 24/7 Global AI portfolio + frontend deployed

**Date:** 2026-05-20
**Live URL (frontend):** https://signal-studio-ten.vercel.app
**Render Blueprint URL:** https://render.com/deploy?repo=https://github.com/clwest/signal-studio

## What changed

Part of the founder-toolkit triplet unpause for the 24/7 Global AI portfolio launch. Single file added:
- `frontend/.env.production` — `VITE_API_URL=https://signal-studio-api.onrender.com`

## Current state

- **Frontend:** ✅ Live on Vercel via GitHub auto-deploy
- **Backend:** ⏳ Blueprint queued. Click the URL above → Render imports `render.yaml` → builds in ~3 min.

## Activation notes

Easiest of the triplet to activate — **no OpenAI dependency at all**. The `POST /api/signals/{id}/generate-action` endpoint returns a hardcoded structured response built from the signal's actual data. Just click Apply on the Blueprint.

- `DATABASE_URL` blank → SQLite. Seed runs on startup via `python -m app.seed`.

## CORS gotcha

If the browser blocks calls after Blueprint activation, add `https://signal-studio-ten.vercel.app` to `CORS_ALLOWED_ORIGINS` in the Render dashboard (the random `-ten` suffix wasn't predictable when render.yaml was written).

## On the 24/7 landing

Card in `src/lib/products.ts` of the `clwest/24-7-ai-global` repo under LAB:
- `status: "demo-ready"`
- `subStatus: "Frontend Live"`
- `url: "https://signal-studio-ten.vercel.app"`

After backend goes live, flip to `status: "shipped"`, `subStatus: "Demo Tier"`.
