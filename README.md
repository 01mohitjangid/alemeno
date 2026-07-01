# AI-Powered Transaction Processing Pipeline

Backend that ingests a raw financial-transactions CSV, processes it
**asynchronously** through a job queue (clean → detect anomalies → LLM classify →
summarise), and serves structured results via a **polling API**.

> Build progress: **Step 1 — Foundation** ✅ · **Step 2 — API layer & job
> lifecycle** ✅ (upload/status/results/list endpoints, CSV validation, async
> enqueue, `pending → processing → completed/failed`). Steps 3–4 add the
> processing pipeline and the LLM integration.

## Stack

| Concern        | Choice                                  |
| -------------- | --------------------------------------- |
| API framework  | FastAPI (uvicorn)                       |
| Database       | PostgreSQL 16 + SQLAlchemy 2 + Alembic  |
| Job queue      | Celery + Redis                          |
| LLM            | OpenAI (`gpt-4o-mini`), optional        |
| Container      | Docker + Docker Compose                 |

## Quick start

```bash
# (optional) enable the real LLM stages — without a key they degrade gracefully
export OPENAI_API_KEY=sk-...

docker compose up --build
```

That single command starts **five** services: `db`, `redis`, a one-shot
`migrate` (runs Alembic), the `api`, and the `worker`. No manual setup steps.

Verify it's alive:

```bash
curl http://localhost:8000/health
# {"status":"healthy","database":"connected"}
```

Interactive API docs: <http://localhost:8000/docs>

> **Port already in use?** If something else holds `:8000`, pick another host
> port — the container port stays 8000:
> ```bash
> API_PORT=8080 docker compose up --build   # then use http://localhost:8080
> ```

## API endpoints

| Method | Path                     | Purpose                                             |
| ------ | ------------------------ | --------------------------------------------------- |
| POST   | `/jobs/upload`           | Upload & validate a CSV, create Job, enqueue task   |
| GET    | `/jobs/{job_id}/status`  | Job status (+ summary once completed)               |
| GET    | `/jobs/{job_id}/results` | Cleaned txns, anomalies, category breakdown, summary|
| GET    | `/jobs?status=`          | List jobs; optional `status=` filter                |

### Example requests

```bash
# 1) Upload — returns a job_id immediately (202)
curl -X POST http://localhost:8000/jobs/upload \
  -F "file=@data/transactions.csv;type=text/csv"
# { "job_id": "…", "status": "pending", "row_count_raw": 95, ... }

# 2) Poll status (pending -> processing -> completed)
curl http://localhost:8000/jobs/<job_id>/status

# 3) Full structured results
curl http://localhost:8000/jobs/<job_id>/results

# 4) List all jobs, or filter by status
curl http://localhost:8000/jobs
curl "http://localhost:8000/jobs?status=completed"
```

Validation is strict: non-CSV uploads and CSVs missing required columns return
`400`; unknown job ids return `404`; an invalid `?status=` returns `422`.

## Architecture

```
            ┌──────────┐        enqueue         ┌──────────┐
  client ──▶│  FastAPI │ ─────────────────────▶ │  Redis   │
            │  (api)   │                        │ (broker) │
            └────┬─────┘                        └────┬─────┘
                 │ read/write                        │ consume
                 ▼                                   ▼
            ┌──────────┐   read/write   ┌────────────────────────┐
            │ Postgres │◀──────────────▶│  Celery worker         │
            │  (db)    │                │  clean → anomaly →     │
            └──────────┘                │  LLM classify → summary│
                                        └────────────────────────┘
```

## Project layout

```
.
├── docker-compose.yml        # db, redis, migrate, api, worker
├── Dockerfile                # shared image for migrate/api/worker
├── requirements.txt
├── alembic/                  # DB migrations (0001 = initial schema)
├── data/transactions.csv     # sample dirty CSV for testing
└── app/
    ├── main.py               # FastAPI app + routers
    ├── config.py             # env-driven settings
    ├── database.py           # engine, session, Base
    ├── models.py             # Job, Transaction, JobSummary
    ├── celery_app.py         # Celery instance
    └── tasks/processing.py   # worker tasks (pipeline)
```

## Data model

- **Job** — `id, filename, status, row_count_raw, row_count_clean, created_at, completed_at, error_message`
- **Transaction** — cleaned fields + `is_anomaly, anomaly_reason, llm_category, llm_raw_response, llm_failed`
- **JobSummary** — `total_spend_inr/usd, top_merchants (JSONB), anomaly_count, narrative, risk_level`

API endpoints (`/jobs/*`) and curl examples land in Step 2.
