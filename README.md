# AI-Powered Transaction Processing Pipeline

A containerised backend that ingests a raw, dirty transactions CSV, processes it
**asynchronously** through a job queue (clean → detect anomalies → LLM classify →
summarise), and serves structured results via a **polling API**.

Everything starts with a single `docker compose up` — no manual setup.

## Stack

| Concern        | Choice                                            |
| -------------- | ------------------------------------------------- |
| API framework  | FastAPI (uvicorn)                                 |
| Database       | PostgreSQL 16 · SQLAlchemy 2 · Alembic migrations |
| Job queue      | Celery + Redis                                    |
| LLM            | OpenAI `gpt-4o-mini` (optional; degrades cleanly) |
| Container      | Docker + Docker Compose                           |
| Tests          | pytest                                            |

## Quick start

```bash
# (optional) enable the real LLM stages — without a key they degrade gracefully
export OPENAI_API_KEY=sk-...

docker compose up --build
```

That single command starts five services: `db`, `redis`, a one-shot `migrate`
(runs Alembic), the `api`, and the `worker`.

```bash
curl http://localhost:8000/health          # {"status":"healthy","database":"connected"}
```

Interactive API docs (Swagger UI): <http://localhost:8000/docs>

> **Port 8000 already in use?** The host port is configurable; the container port
> stays 8000:
> ```bash
> API_PORT=8080 docker compose up --build   # then use http://localhost:8080
> ```

### One-command smoke test

```bash
./scripts/smoke_test.sh                             # against :8000
BASE_URL=http://localhost:8080 ./scripts/smoke_test.sh
```

## API endpoints

| Method | Path                     | Purpose                                              |
| ------ | ------------------------ | --------------------------------------------------- |
| POST   | `/jobs/upload`           | Validate a CSV, create a Job, enqueue processing    |
| GET    | `/jobs/{job_id}/status`  | Job status (+ summary once completed)               |
| GET    | `/jobs/{job_id}/results` | Cleaned txns, anomalies, category breakdown, summary|
| GET    | `/jobs?status=`          | List jobs; optional `status=` filter                |

### Examples

```bash
# 1) Upload -> returns a job_id immediately (202 Accepted)
curl -X POST http://localhost:8000/jobs/upload \
  -F "file=@data/transactions.csv;type=text/csv"
# {"job_id":"…","status":"pending","filename":"transactions.csv","row_count_raw":95,…}

# 2) Poll status (pending -> processing -> completed)
curl http://localhost:8000/jobs/<job_id>/status

# 3) Full structured results
curl http://localhost:8000/jobs/<job_id>/results

# 4) List / filter
curl http://localhost:8000/jobs
curl "http://localhost:8000/jobs?status=completed"
```

<details>
<summary>Example <code>/results</code> response (abridged)</summary>

```json
{
  "job_id": "…",
  "status": "completed",
  "row_count_raw": 95,
  "row_count_clean": 85,
  "summary": {
    "total_spend_inr": 1339923.00,
    "total_spend_usd": 74185.14,
    "top_merchants": [
      {"merchant": "IRCTC", "total_spend": 450697.69, "transactions": 12},
      {"merchant": "Jio Recharge", "total_spend": 270255.97, "transactions": 12},
      {"merchant": "Flipkart", "total_spend": 227539.88, "transactions": 12}
    ],
    "anomaly_count": 10,
    "narrative": "The total spending reached … 10 anomalies raise concerns …",
    "risk_level": "high"
  },
  "transactions": [
    {"txn_id":"TXN1065","date":"2024-09-04","merchant":"Flipkart","amount":10882.55,
     "currency":"INR","status":"SUCCESS","category":"Shopping","is_anomaly":false,
     "llm_category":null,"llm_failed":false, "...": "..."}
  ],
  "anomalies": [
    {"txn_id":"TXN2003","merchant":"IRCTC","amount":193647.29,"currency":"INR",
     "is_anomaly":true,
     "anomaly_reason":"Statistical outlier: amount 193647.29 exceeds 3x account median (9837.85)"}
  ],
  "category_breakdown": {
    "Travel":   {"INR": 450697.69, "USD": 31122.91},
    "Shopping": {"INR": 280715.73},
    "Food":     {"INR": 67045.08, "USD": 43062.23}
  }
}
```
</details>

Validation is strict: non-CSV → `400`; missing columns → `400`; oversized → `413`;
unknown job → `404`; invalid `?status=` → `422`.

## Processing pipeline (worker)

When a job is dequeued, `app/services/pipeline.py` runs, in order:

1. **Clean (§5a)** — dates → ISO 8601 (handles `DD-MM-YYYY`, `YYYY/MM/DD`,
   `YYYY-MM-DD`), strip `$`/separators from amounts, upper-case status + currency,
   fill blank category with `Uncategorised`, remove exact-duplicate rows.
2. **Detect anomalies (§5b)** — flag `amount > 3× the account's median`
   (statistical outlier) and `USD on a domestic-only merchant` (Swiggy, Ola,
   IRCTC, Zomato, …). Reasons stored in `anomaly_reason`; a row can trip both.
3. **Persist** — cleaned rows written as `Transaction`s (idempotent: a re-run
   replaces the job's rows instead of duplicating).
4. **LLM classify (§5c)** — the `Uncategorised` rows are classified in **batches**
   (one call per batch, not per row) into Food/Shopping/Travel/Transport/
   Utilities/Cash Withdrawal/Entertainment/Other → `llm_category`.
5. **Narrative summary (§5d)** — a **single** LLM call produces the `narrative` +
   `risk_level`; the factual stats (spend by currency, top-3 merchants, anomaly
   count) are computed **deterministically in code** and stored in `JobSummary`.

On the sample CSV: **95 raw → 85 clean** (10 dupes), **10 anomalies** (5 outliers +
5 USD-on-Zomato), 13 rows LLM-classified.

### LLM resilience (§5e)

- Retries transient failures (rate-limit / timeout / 5xx) with **exponential
  backoff** via `tenacity`; the SDK's own retry is disabled so ours is
  authoritative. Auth/bad-request errors fail fast (a retry can't help).
- If a batch ultimately fails, those rows are marked **`llm_failed`** and the
  pipeline **continues — the job is never failed** because of the LLM.
- **No API key?** The system runs end-to-end: classification is skipped
  (`llm_failed=true`), and the summary uses computed stats with a heuristic
  `risk_level`.

## Data model

- **Job** — `id, filename, status, row_count_raw, row_count_clean, created_at, completed_at, error_message`
- **Transaction** — cleaned fields + `is_anomaly, anomaly_reason, llm_category, llm_raw_response, llm_failed`
- **JobSummary** — `total_spend_inr/usd, top_merchants (JSONB), anomaly_count, narrative, risk_level`

## Architecture

See [docs/architecture.md](docs/architecture.md) (Mermaid, renders on GitHub) and
the editable [docs/architecture.drawio](docs/architecture.drawio).

```
        ┌──────────┐   HTTP    ┌──────────┐  enqueue   ┌──────────┐
 client ├─ upload ─▶│ FastAPI  ├──────────▶│  Redis   │
        │◀─ poll ───┤  (api)   │           │ (broker) │
        └──────────┘└────┬─────┘           └────┬─────┘
                    read │ Job                   │ deliver
                    write▼ results          consume▼
                    ┌──────────┐  write   ┌────────────────────────┐  classify+
                    │ Postgres │◀─────────┤  Celery worker         ├─ narrative ─▶ OpenAI
                    │  (db)    │          │  clean→anomaly→LLM→sum │
                    └──────────┘          └────────────────────────┘
```

## Project structure

```
.
├── docker-compose.yml          # db, redis, migrate, api, worker
├── Dockerfile                  # shared image (non-root user)
├── requirements.txt
├── pytest.ini
├── alembic/                    # migrations (0001 = initial schema)
├── data/transactions.csv       # sample dirty CSV
├── docs/architecture.{md,drawio}
├── scripts/smoke_test.sh
├── tests/                      # unit tests (cleaning, anomaly)
└── app/
    ├── main.py                 # FastAPI app + router mount
    ├── config.py               # env-driven settings
    ├── database.py             # engine, session, Base
    ├── models.py               # Job, Transaction, JobSummary
    ├── schemas.py              # Pydantic response models
    ├── celery_app.py           # Celery instance
    ├── api/routes/jobs.py      # the 4 endpoints
    ├── services/
    │   ├── storage.py          # upload storage + CSV validation
    │   ├── cleaning.py         # §5a normalisation + dedupe
    │   ├── anomaly.py          # §5b outlier + USD-domestic
    │   ├── llm.py              # OpenAI calls + retry/backoff
    │   └── pipeline.py         # orchestration
    └── tasks/processing.py     # Celery process_job (lifecycle)
```

## Tests

```bash
docker compose exec api pytest        # 9 unit tests (cleaning + anomaly)
```

## Configuration

All via environment (safe defaults; Compose injects the DB/Redis URLs):

| Variable                    | Default        | Purpose                             |
| --------------------------- | -------------- | ----------------------------------- |
| `OPENAI_API_KEY`            | *(empty)*      | Enables LLM stages                  |
| `OPENAI_MODEL`              | `gpt-4o-mini`  | Chat model                          |
| `API_PORT`                  | `8000`         | Host port for the API               |
| `LLM_BATCH_SIZE`            | `20`           | Transactions per classification call|
| `LLM_MAX_RETRIES`           | `3`            | Retries per LLM call                |
| `ANOMALY_MEDIAN_MULTIPLIER` | `3.0`          | Outlier threshold                   |
| `DOMESTIC_MERCHANTS`        | Swiggy,Ola,…   | India-only brands for USD check     |

## Scaling notes (100× traffic)

- **DB connections** — a pool per API/worker replica; front Postgres with
  **PgBouncer** and tune pool sizes.
- **Uploads** — the shared Docker volume becomes **object storage (S3)** with
  pre-signed uploads; the worker streams from S3.
- **Large CSVs** — stream/`COPY`-load and process in chunks instead of reading the
  whole file into memory; split one job into per-chunk subtasks.
- **Workers** — scale Celery horizontally; isolate LLM-bound tasks on their own
  queue so slow LLM calls don't starve fast ones.
- **Reliability** — task time limits + a reaper for jobs stuck in `processing`;
  pagination on `GET /jobs`.
```
