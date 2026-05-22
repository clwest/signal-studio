# SignalStudio

Signal clustering + evidence-backed action cards for market research.

## Quick Start

```bash
bash start.sh
# Backend:  http://localhost:8080
# Frontend: http://localhost:5173
```

## Docker / fleet-net

SignalStudio ships a `docker-compose.yml` for the laptop-local fleet
network. Three containers (`signal_studio_postgres`,
`signal_studio_api`, `signal_studio_web`) on the shared `fleet-net`.

```bash
docker network create fleet-net 2>/dev/null || true
cp .env.example .env  # edit OPENAI_API_KEY + SECRET_KEY
docker compose up -d                                              # prod-like
docker compose -f docker-compose.yml -f docker-compose.dev.yml up # dev
```

Reach it at `http://localhost:8080/api/health` and
`http://localhost:5173/`. Fleet pattern reference:
[`/Users/donkeyking/development/infra/README.md`](/Users/donkeyking/development/infra/README.md).
