# Local Setup Guide

> **End-to-End Platform Engineering of a Serverless ETL Pipeline for Chess Game Analysis and Puzzle Generation on AWS**

This guide walks you through running the project locally using Docker Compose. No AWS account is required — the full pipeline (game extraction, Stockfish analysis, puzzle storage) runs inside local containers.

---

## Prerequisites

Before you begin, make sure the following are installed.

| Tool | Minimum Version | Check |
|---|---|---|
| [Docker](https://docs.docker.com/get-docker/) | 24.x | `docker --version` |
| [Docker Compose](https://docs.docker.com/compose/install/) | 2.x | `docker compose version` |
| [Git](https://git-scm.com/) | any | `git --version` |

> **Note for WSL users** — Docker Desktop must be running on Windows with WSL integration enabled for your distro (`Docker Desktop → Settings → Resources → WSL Integration`).

---

## 1. Clone the Repository

```bash
git clone https://github.com/Data-Bishop/chess-puzzle-generator.git
cd chess-puzzle-generator
```

---

## 2. Configure Environment Variables

Copy the environment template and open it for editing.

```bash
cp .env.template .env
```

The table below describes every variable. For local development you only **need** to set the ones marked **Required**.

| Variable | Required | Default | Description |
|---|---|---|---|
| `POSTGRES_USER` | | `databishop` | PostgreSQL username |
| `POSTGRES_PASSWORD` | | `databishop` | PostgreSQL password |
| `POSTGRES_DB` | | `chess_puzzles` | PostgreSQL database name |
| `DATABASE_URL` | | *(derived)* | Full connection string — leave blank to use the default |
| `REDIS_URL` | | `redis://redis:6379/0` | Redis connection string |
| `ENVIRONMENT` | | `development` | `development` or `production` |
| `WORKER_MODE` | ✅ | `local` | `local` (Docker worker) or `lambda` (AWS Lambda) |
| `LAMBDA_SECRET` | | — | Only needed when `WORKER_MODE=lambda` |
| `AWS_REGION` | | `eu-north-1` | Only needed when `WORKER_MODE=lambda` |
| `LAMBDA_ETL_ARN` | | — | Only needed when `WORKER_MODE=lambda` |

For local development your `.env` should look like this:

```dotenv
POSTGRES_USER=databishop
POSTGRES_PASSWORD=databishop
POSTGRES_DB=chess_puzzles
REDIS_URL=redis://redis:6379/0
ENVIRONMENT=development
WORKER_MODE=local
```

> **`WORKER_MODE=local`** runs puzzle generation inside a Docker container with Stockfish bundled. No AWS credentials are needed.

---

## 3. Start the Stack

```bash
docker compose up --build
```

This builds and starts five services:

| Service | Container | Port | Role |
|---|---|---|---|
| `postgres` | `postgres` | `5432` | Stores jobs and generated puzzles |
| `redis` | `redis` | `6379` | Job queue and rate-limit state |
| `backend` | `backend` | `8000` | FastAPI application |
| `worker` | `worker` | — | Pulls jobs from Redis, runs Stockfish |
| `nginx` | `nginx` | `80` | Serves the frontend and proxies `/api/*` to FastAPI |

The first build takes a few minutes because the worker image compiles Stockfish. Subsequent starts are fast.

To run in detached mode (background):

```bash
docker compose up --build -d
```

---

## 4. Verify the Stack is Running

Once all containers are healthy, run the following checks.

**Health endpoint:**

```bash
curl http://localhost:8000/health
```

```json
{ "status": "healthy" }
```

**Root endpoint:**

```bash
curl http://localhost:8000/
```

```json
{
  "message": "Chess Puzzle Generator API",
  "version": "0.1.0",
  "status": "online"
}
```

**Frontend:**

Open [http://localhost](http://localhost) in your browser. You should see the puzzle generator UI.

---

## 5. Generate Your First Puzzles

### Using the UI

1. Open [http://localhost](http://localhost)
2. Enter a valid Chess.com username (e.g. `hikaru`, `magnuscarlsen`)
3. Optionally set filters — date range, time control, rating range
4. Click **Generate Puzzles**
5. The job status will update from `pending → processing → generating_puzzles → completed`
6. Once complete, puzzles load automatically — click any puzzle to start solving

### Using the API directly

**Submit a job:**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{ "username": "hikaru" }'
```

```json
{
  "id": "3f6a1b2c-...",
  "username": "hikaru",
  "status": "pending",
  "created_at": "2026-04-29T10:00:00Z",
  ...
}
```

**Poll job status:**

```bash
curl http://localhost:8000/jobs/<job_id>
```

**Fetch generated puzzles:**

```bash
curl http://localhost:8000/jobs/<job_id>/puzzles
```

**Delete a job and its puzzles:**

```bash
curl -X DELETE http://localhost:8000/jobs/<job_id>
```

---

## 6. API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/jobs` | Submit a new puzzle generation job |
| `GET` | `/jobs/{job_id}` | Get job status |
| `GET` | `/jobs/{job_id}/puzzles` | List generated puzzles for a job |
| `DELETE` | `/jobs/{job_id}` | Delete a job and its puzzles |

> Interactive API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger UI) and [http://localhost:8000/redoc](http://localhost:8000/redoc).

### Job Status Lifecycle

```
pending → processing → generating_puzzles → completed
                    ↘                     ↘
                     failed                failed
```

| Status | Meaning |
|---|---|
| `pending` | Job is queued, waiting for the worker to pick it up |
| `processing` | Worker is fetching games from Chess.com |
| `generating_puzzles` | Stockfish is analysing positions |
| `completed` | Puzzles are ready |
| `failed` | An error occurred — check `error_message` in the response |

### Filters

The `POST /jobs` body accepts optional filters:

```json
{
  "username": "hikaru",
  "date_from": "2024-01-01T00:00:00Z",
  "date_to":   "2024-12-31T23:59:59Z",
  "time_control": "blitz",
  "min_rating": 1800,
  "max_rating": 2200
}
```

| Field | Type | Description |
|---|---|---|
| `username` | `string` | Chess.com username *(required)* |
| `date_from` | `datetime` | Only include games played after this date |
| `date_to` | `datetime` | Only include games played before this date |
| `time_control` | `string` | `"bullet"`, `"blitz"`, `"rapid"`, or `"classical"` |
| `min_rating` | `integer` | Minimum opponent rating |
| `max_rating` | `integer` | Maximum opponent rating |

### Rate Limiting

Job creation is limited to **5 requests per hour per IP address**. Exceeding the limit returns:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 3542
```

---

## 7. Running Tests

Tests require no running containers — they use an in-memory SQLite database and mocked external services.

**Install test dependencies:**

```bash
cd backend
pip install -r requirements-test.txt
```

**Run the full test suite:**

```bash
pytest
```

**Run with coverage report:**

```bash
pytest --cov=app --cov-report=term-missing
```

**Run a specific test file:**

```bash
pytest tests/test_api.py
pytest tests/test_puzzle_generator.py
```

---

## 8. Common Commands

**View logs for a specific service:**

```bash
docker compose logs -f backend
docker compose logs -f worker
```

**Restart a single service:**

```bash
docker compose restart backend
```

**Stop all containers:**

```bash
docker compose down
```

**Stop and wipe all data** (resets the database and Redis):

```bash
docker compose down -v
```

**Rebuild a single service after a code change:**

```bash
docker compose up --build backend
```

---

## 9. Project Structure

```
chess-puzzle-generator/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app and all endpoints
│   │   ├── worker.py          # Local background job processor
│   │   ├── puzzle_generator.py # Stockfish analysis and tactic detection
│   │   ├── chesscom_client.py  # Chess.com API client
│   │   ├── models.py          # SQLAlchemy ORM models (Job, Puzzle)
│   │   ├── schemas.py         # Pydantic request/response schemas
│   │   ├── config.py          # Settings loaded from environment
│   │   ├── job_queue.py       # Redis queue management
│   │   └── rate_limiter.py    # Sliding window rate limiter
│   ├── tests/                 # Backend test suite
│   ├── Dockerfile             # FastAPI image
│   ├── Dockerfile.worker      # Worker image (includes Stockfish)
│   └── requirements.txt
├── frontend/
│   └── index.html             # Single-page application
├── docker/
│   ├── nginx/nginx.conf       # Nginx reverse proxy config
│   └── postgres/init/         # Database initialisation SQL
├── lambda/                    # AWS Lambda functions (cloud mode)
│   ├── etl/                   # Game extraction Lambda
│   └── puzzles/               # Puzzle generator Lambda
├── terraform/                 # Infrastructure as Code
├── docs/                      # Documentation
└── docker-compose.yml
```

---

## 10. Troubleshooting

**Port 80 already in use:**

```bash
# Find what's using port 80
sudo lsof -i :80
# Or change the Nginx port in docker-compose.yml
ports:
  - "8080:80"
```

**Worker not picking up jobs:**

```bash
# Check worker logs
docker compose logs -f worker

# Verify Redis is reachable
docker compose exec redis redis-cli ping
# Expected: PONG
```

**Database connection errors:**

```bash
# Check postgres logs
docker compose logs postgres

# Verify postgres is healthy
docker compose ps
# postgres container should show "(healthy)"
```

**Stockfish not found inside the worker:**

```bash
# Confirm Stockfish is installed in the worker container
docker compose exec worker which stockfish
# Expected: /usr/games/stockfish
```

**Chess.com username not found:**

The Chess.com API is public and rate-limited. If a username returns no games it may be because the account is private, has no games in the selected date range, or the username is incorrect (Chess.com usernames are case-insensitive but must be exact).
