# AI-Powered Transaction Processing Pipeline

Upload a messy transactions CSV → it's cleaned, anomaly-checked, LLM-classified,
and summarised **asynchronously** through a job queue, with results served via a
**polling API** and a small **web dashboard**.

## 🚀 Run it

```bash
docker compose up --build
```

That one command starts everything (API, worker, PostgreSQL, Redis). Then open:

| What | URL |
| ---- | --- |
| 🖥️  **Dashboard** | http://localhost:8000/ui |
| 📚  API docs (Swagger) | http://localhost:8000/docs |
| ❤️  Health check | http://localhost:8000/health |

> **Optional LLM:** run `export OPENAI_API_KEY=sk-...` before the command to enable
> real AI classification. Without it, the app still works — the LLM stages degrade
> gracefully.
>
> **Port 8000 busy?** Use `API_PORT=8080 docker compose up --build` → then use `:8080`.

## Try it

Upload the included sample CSV via the dashboard, or with curl:

```bash
# upload -> returns a job_id immediately
curl -X POST http://localhost:8000/jobs/upload -F "file=@data/transactions.csv;type=text/csv"

# poll status, then get full results
curl http://localhost:8000/jobs/<job_id>/status
curl http://localhost:8000/jobs/<job_id>/results
```

Or run the one-shot smoke test: `./scripts/smoke_test.sh`

## API endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| POST | `/jobs/upload` | Validate a CSV, create a job, enqueue processing |
| GET | `/jobs/{id}/status` | Job status (+ summary once completed) |
| GET | `/jobs/{id}/results` | Cleaned txns, anomalies, category breakdown, summary |
| GET | `/jobs?status=` | List jobs (optional status filter) |

## What the pipeline does

When a job runs, the worker executes in order:

1. **Clean** — dates → ISO 8601, strip `$` from amounts, upper-case status/currency, fill blank category, remove duplicates.
2. **Detect anomalies** — flag amounts > 3× the account median, and USD charged on India-only merchants (Swiggy, Ola, IRCTC, …).
3. **LLM classify** — categorise the uncategorised rows in **batches** (Food, Shopping, Travel, …).
4. **Summarise** — one LLM call for a narrative + risk level; spend totals and top merchants computed in code.

LLM calls retry with exponential backoff; if they still fail, the batch is marked `llm_failed` and the job continues.

## Stack

FastAPI · Celery + Redis · PostgreSQL (SQLAlchemy + Alembic) · OpenAI `gpt-4o-mini` · Docker Compose

## Tests

```bash
docker compose exec api pytest
```

## More

- **Architecture diagram:** [docs/architecture.md](docs/architecture.md) · [docs/architecture.drawio](docs/architecture.drawio)
- **Config** (env vars, all optional): `OPENAI_API_KEY`, `OPENAI_MODEL`, `API_PORT`, `LLM_BATCH_SIZE`, `LLM_MAX_RETRIES`, `ANOMALY_MEDIAN_MULTIPLIER`, `DOMESTIC_MERCHANTS`
