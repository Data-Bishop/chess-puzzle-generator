# Chess Puzzle Generator

A web application that generates personalized chess puzzles from your Chess.com games. Enter any Chess.com username and get tactical puzzles extracted from real games, powered by Stockfish analysis.

> **If you find this project useful, please consider giving it a star!** It helps others discover it and motivates continued development.

## Features

- **Puzzle Generation**: Automatically extracts tactical positions from Chess.com games
- **Interactive Solver**: Solve puzzles on an interactive chessboard with move validation
- **Filtering Options**: Filter games by date range, time control (bullet/blitz/rapid/daily), and rating
- **Progress Tracking**: Track solved puzzles with visual progress bar
- **Hints & Solutions**: Get hints or view the full solution when stuck
- **Job History**: Recent jobs saved locally for quick access
- **Rate Limiting**: Fair usage limits (5 jobs per hour per user)
- **Auto-cleanup**: Puzzles automatically expire after 24 hours

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/Data-Bishop/chess-puzzle-generator.git
cd chess-puzzle-generator
```

### 2. Create Environment File

```bash
cp .env.template .env
```

The default values work for local development.

### 3. Start All Services

```bash
docker-compose up -d
```

This starts:
- **PostgreSQL** (port 5432) - Database
- **Redis** (port 6379) - Job queue and rate limiting
- **Backend API** (port 8000) - FastAPI server
- **Worker** - Background job processor with Stockfish
- **Nginx** (port 3000) - Serves frontend and proxies API

### 4. Access the Application

Open your browser and go to: **http://localhost:3000**

## Usage Guide

### Generating Puzzles

1. **Enter a Chess.com username** in the "Generate Puzzles" form
2. *(Optional)* Click "Advanced Filters" to filter by:
   - **Date Range**: Only include games from a specific period
   - **Time Control**: Bullet, Blitz, Rapid, or Daily games
   - **Rating Range**: Filter by opponent rating
3. Click **"Generate Puzzles"**
4. Wait for the job to complete (usually 1-3 minutes depending on game count)
5. Click **"Start Solving"** when puzzles are ready

### Solving Puzzles

- **Make moves** by dragging pieces on the board
- **Green feedback** = Correct move
- **Red feedback** = Incorrect, try again
- Use **Hint** to highlight the piece to move
- Use **Solution** to see all remaining moves
- Use **Reset** to restart the current puzzle
- Navigate between puzzles using **← →** buttons or the puzzle list

### Loading Previous Jobs

- Recent jobs appear in the "Recent Jobs" section
- Click **Load** to resume a previous session
- Click **×** to remove from history

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Nginx     │────▶│  Backend    │
│  (Browser)  │     │  (Proxy)    │     │  (FastAPI)  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                         ┌─────────────────────┼─────────────────────┐
                         │                     │                     │
                         ▼                     ▼                     ▼
                  ┌─────────────┐       ┌─────────────┐        ┌─────────────┐
                  │  PostgreSQL │       │    Redis    │        │   Worker    │
                  │  (Database) │       │   (Queue)   │◀─────▶│ (Stockfish) │
                  └─────────────┘       └─────────────┘        └─────────────┘
```

### Components

| Component | Description |
|-----------|-------------|
| **Frontend** | Single-page app with chessboard.js and chess.js |
| **Backend** | FastAPI REST API for job management |
| **Worker** | Background processor that fetches games and generates puzzles |
| **PostgreSQL** | Stores jobs and puzzles |
| **Redis** | Job queue and rate limiting |
| **Stockfish** | Chess engine for position analysis |

## Project Structure

```
chess-puzzle-generator/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── worker.py            # Background job processor
│   │   ├── models.py            # Database models
│   │   ├── schemas.py           # API schemas
│   │   ├── chesscom_client.py   # Chess.com API client
│   │   ├── puzzle_generator.py  # Stockfish puzzle extraction
│   │   ├── job_queue.py         # Redis queue management
│   │   ├── rate_limiter.py      # Rate limiting
│   │   ├── database.py          # Database connection
│   │   └── config.py            # Configuration
│   ├── Dockerfile               # Backend container
│   ├── Dockerfile.worker        # Worker container (with Stockfish)
│   └── requirements.txt         # Python dependencies
├── frontend/
│   └── index.html               # Web UI (single file)
├── database/
│   └── init/
│       └── 01-init.sql          # Database schema
├── docker/
│   └── nginx/
│       └── nginx.conf           # Nginx configuration
├── docker-compose.yml           # Service orchestration
├── .env.template                # Environment template
└── README.md                    # This file
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/jobs` | Create a new puzzle generation job |
| `GET` | `/jobs/{job_id}` | Get job status |
| `GET` | `/jobs/{job_id}/puzzles` | Get puzzles for a job |
| `DELETE` | `/jobs/{job_id}` | Delete a job and its puzzles |

### Create Job Request

```json
{
  "username": "hikaru",
  "date_from": "2024-01-01T00:00:00Z",
  "date_to": "2024-12-31T23:59:59Z",
  "time_control": "blitz",
  "min_rating": 1000,
  "max_rating": 2000
}
```

All fields except `username` are optional.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `databishop` | Database username |
| `POSTGRES_PASSWORD` | `databishop` | Database password |
| `POSTGRES_DB` | `chess_puzzles` | Database name |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |
| `ENVIRONMENT` | `development` | Environment mode |

### Rate Limits

- **5 jobs per hour** per IP address
- Configurable in `backend/app/rate_limiter.py`

### Puzzle Settings

- **Max 20 puzzles** per job
- **Max 2 puzzles** per game
- **24-hour TTL** for puzzles (auto-deleted)
- Configurable in `backend/app/worker.py`

## Troubleshooting

### Services won't start

```bash
# Check service status
docker-compose ps

# View logs for a specific service
docker logs backend
docker logs worker
docker logs postgres
```

### "Submitting..." stuck

The backend might not be running:
```bash
# Restart all services
docker-compose restart

# Or rebuild if code changed
docker-compose up -d --build
```

### No puzzles generated

- The Chess.com user might not have recent games
- Try a different username (e.g., `hikaru`, `magnuscarlsen`)
- Check worker logs: `docker logs worker`

### Database issues

```bash
# Reset the database (WARNING: deletes all data)
docker-compose down -v
docker-compose up -d
```

## Development

### Running Backend Locally (without Docker)

```bash
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt

# Start the API
uvicorn app.main:app --reload --port 8000

# Start the worker (in another terminal)
python -m app.worker
```

Requires PostgreSQL, Redis, and Stockfish installed locally.

### Viewing API Documentation

FastAPI auto-generates API docs:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Tech Stack

- **Frontend**: HTML, CSS, JavaScript, chessboard.js, chess.js
- **Backend**: Python, FastAPI, SQLAlchemy, Pydantic
- **Database**: PostgreSQL
- **Queue**: Redis
- **Chess Engine**: Stockfish
- **Containerization**: Docker, Docker Compose
- **Web Server**: Nginx

## Roadmap

Currently working on:
- Optimizing the puzzle generation process for faster and better analysis
- Supporting multiple concurrent job processing
- CLI tool for generating puzzles from the command line
- Infrastructure as Code (IaC) for AWS deployment with Terraform
- Serverless architecture migration (Lambda etc.)

## Contributing

Feedback and suggestions are welcome! Feel free to open an issue or submit a pull request.

## License

MIT License - See [LICENSE](LICENSE) file for details.
