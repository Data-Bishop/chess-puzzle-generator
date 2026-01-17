# Chess Puzzle Generator

A web application that generates personalized chess puzzles from real Chess.com games. Built as a full-stack data engineering and platform engineering project.

## Project Overview

**What it does:**
- Fetches games from Chess.com for any username
- Analyzes positions with Stockfish to find tactical opportunities
- Generates interactive puzzles users can solve on a chessboard
- No login required - stateless, public access with temporary data storage

## Project Structure

```
chess-puzzle-generator/
├── backend/
│   ├── app/
│   │   ├── config.py          # Environment configuration
│   │   ├── database.py        # Database connection
│   │   ├── models.py          # SQLAlchemy ORM models
│   │   ├── schemas.py         # Pydantic request/response schemas
│   │   └── main.py            # FastAPI application
│   ├── Dockerfile             # Backend container
│   └── requirements.txt       # Python dependencies
├── database/
│   └── init/
│       └── 01-init.sql        # PostgreSQL schema
├── docker/
│   └── nginx/
│       └── nginx.conf         # Nginx configuration
├── frontend/
│   └── index.html             # Web UI
├── .env                       # Local environment variables (not committed)
├── .env.template              # Environment variable template
├── .gitignore                 # Git ignore rules
├── docker-compose.yml         # Docker orchestration
└── README.md                  # This file
```

## Contributing

This is a personal project, but feedback and suggestions are welcome!

## License

MIT License - See LICENSE file for details
