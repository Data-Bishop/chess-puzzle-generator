# End-to-End Platform Engineering of a Serverless ETL Pipeline for Chess Game Analysis and Puzzle Generation on AWS

A cloud-native platform that ingests Chess.com game archives, runs batch Stockfish analysis via AWS Lambda, and delivers personalised tactical puzzles through an interactive web UI — fully deployed on AWS with Terraform IaC and GitHub Actions CI/CD.

[![CI](https://github.com/Data-Bishop/chess-puzzle-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/Data-Bishop/chess-puzzle-generator/actions/workflows/ci.yml)
[![Deploy](https://github.com/Data-Bishop/chess-puzzle-generator/actions/workflows/deploy.yml/badge.svg)](https://github.com/Data-Bishop/chess-puzzle-generator/actions/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What This Project Demonstrates

| Discipline | What was built |
|---|---|
| **Serverless ETL** | Two-stage AWS Lambda pipeline: game extraction (Python 3.12 zip) → Stockfish analysis (container image) |
| **Infrastructure as Code** | Full Terraform configuration — EC2, Lambda, S3, ECR, SSM, IAM, DynamoDB, Elastic IP |
| **CI/CD** | GitHub Actions — tests on every push, automated deploy on CI pass via OIDC (no static keys) |
| **Containerisation** | Docker Compose stack (Nginx, FastAPI, PostgreSQL, Redis, Worker) for local parity with production |
| **Secrets management** | SSM Parameter Store injects secrets into EC2 at boot — zero manual configuration post-deploy |
| **Event-driven architecture** | Lambda → EC2 callback pattern; async job invocation with status polling |
| **Platform engineering** | Bootstrap pattern for one-time infra (state backend, OIDC provider, deploy role) separate from app infra |

---

## Architecture

---

## Tech Stack

**Cloud & Infrastructure**

![AWS](https://img.shields.io/badge/AWS-Lambda%20·%20EC2%20·%20S3%20·%20ECR%20·%20SSM%20·%20DynamoDB-FF9900?logo=amazonaws&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-IaC-7B42BC?logo=terraform&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI%2FCD-2088FF?logo=githubactions&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

**Application**

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Nginx](https://img.shields.io/badge/Nginx-Reverse_Proxy-009639?logo=nginx&logoColor=white)
![Stockfish](https://img.shields.io/badge/Stockfish-Chess_Engine-grey)

---

## UI

### Job Submission

Enter a Chess.com username and optional filters — date range, time control, and rating range — to kick off the ETL pipeline.

![Job Submission UI](docs/assets/submit_job.png)

### Pipeline in Progress

Once submitted, the UI polls job status in real time as it moves through the pipeline. Here Stockfish is analysing 845 games fetched from Chess.com.

![Generating Puzzles](docs/assets/generating_puzzles.png)

### Puzzles Ready

When the pipeline completes, the results are summarised — games analysed, puzzles generated — with a direct link to start solving.

![Puzzles Ready](docs/assets/generated_puzzles.png)

### Puzzle Solver

Solve puzzles on an interactive chessboard with move validation, tactic theme, difficulty rating, hint, and full solution reveal. Progress is tracked across all 20 puzzles.

![Puzzle Solver UI](docs/assets/solve_puzzles.png)

---

## Quick Start

### Run Locally

No AWS account needed. The full pipeline runs inside Docker containers.

```bash
git clone https://github.com/Data-Bishop/chess-puzzle-generator.git
cd chess-puzzle-generator

cp .env.template .env        # default values work for local dev

docker compose up --build
```

Open **http://localhost** — the app is ready.

Full guide → [docs/local-setup.md](docs/local-setup.md)

---

### Deploy to AWS

One-time bootstrap, then every push to `main` deploys automatically.

```bash
# 1. Bootstrap — run once from your machine
cd bootstrap && terraform init && terraform apply

# 2. Add secrets to GitHub → Settings → Environments → production
#    (see cloud-setup.md for the full list)

# 3. Push to main — CI runs, then CD deploys everything
git push origin main
```

Full guide → [docs/cloud-setup.md](docs/cloud-setup.md)

---

## Documentation

| Document | Description |
|---|---|
| [Local Setup](docs/local-setup.md) | Run the full stack locally with Docker Compose |
| [Cloud Setup](docs/cloud-setup.md) | Deploy to AWS with Terraform and GitHub Actions |

---

## License

[MIT](LICENSE)
