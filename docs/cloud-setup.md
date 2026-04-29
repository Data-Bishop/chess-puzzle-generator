# Cloud Setup Guide

> **End-to-End Platform Engineering of a Serverless ETL Pipeline for Chess Game Analysis and Puzzle Generation on AWS**

This guide covers deploying the project to AWS. The cloud setup replaces the local Docker worker with two AWS Lambda functions — one for game extraction (ETL) and one for Stockfish puzzle generation — while the FastAPI backend and UI continue to run on an EC2 instance behind Nginx.

---

## Overview

The deployment is fully automated. Once the one-time bootstrap is complete, every push to `main` triggers a CI/CD pipeline that tests, builds, and deploys the entire stack.

```
Bootstrap (once)        CI / CD (every push to main)
─────────────────       ─────────────────────────────────────────────
S3 state bucket    →    CI: tests · lint · terraform validate
DynamoDB lock      →    CD: push image → ECR
GitHub OIDC        →        terraform apply → all AWS resources
Deploy IAM role    →        EC2 self-configures via SSM + user_data
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| AWS account | With permissions to create IAM roles, Lambda, EC2, S3, DynamoDB, SSM, ECR |
| [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) | Configured with credentials (`aws configure`) |
| [Terraform >= 1.5](https://developer.hashicorp.com/terraform/install) | Used for bootstrap and reviewed locally |
| [Git](https://git-scm.com/) | To push the trigger commit |
| GitHub repository | Must be **public** or have GitHub Actions enabled |

---

## Architecture at a Glance

| Layer | Service | Role |
|---|---|---|
| Compute | EC2 t3.small (Amazon Linux 2023) | Runs Nginx, FastAPI, PostgreSQL, Redis via Docker Compose |
| Serverless | AWS Lambda (python3.12 zip) | ETL — fetches games from Chess.com, stores to S3 |
| Serverless | AWS Lambda (container + Stockfish) | Puzzle generation — reads S3, runs Stockfish, callbacks to EC2 |
| Storage | S3 | Temporary game data (1-day auto-expiry) |
| Secrets | SSM Parameter Store | Injects secrets into EC2 at boot |
| Registry | ECR | Stores the puzzle generator container image |
| CI/CD | GitHub Actions | Tests on every push; deploys on CI pass |
| IaC | Terraform | Manages all AWS resources with remote state |

---

## Step 1 — Bootstrap (One-Time)

The bootstrap creates the resources that Terraform itself needs to operate: a remote state bucket, a state lock table, and the IAM role that GitHub Actions will assume via OIDC. This step is run **once** from your local machine and never again.

### 1.1 — Navigate to the bootstrap directory

```bash
cd bootstrap
```

### 1.2 — Initialise Terraform

```bash
terraform init
```

### 1.3 — Review the plan

```bash
terraform plan
```

Bootstrap creates the following resources:

| Resource | Purpose |
|---|---|
| `aws_s3_bucket` | Stores Terraform state with versioning and AES-256 encryption |
| `aws_dynamodb_table` | Prevents concurrent `terraform apply` runs (state locking) |
| `aws_iam_openid_connect_provider` | Trusts GitHub Actions tokens — no static AWS keys needed |
| `aws_iam_role` (github-deploy) | The role GitHub Actions assumes; scoped to project resources only |

> **Note** — If your AWS account already has an OIDC provider for `token.actions.githubusercontent.com`, import it before applying to avoid a conflict:
> ```bash
> terraform import aws_iam_openid_connect_provider.github <existing-provider-arn>
> ```

### 1.4 — Apply

```bash
terraform apply
```

When it completes, note the outputs — you will need them in the next step.

```
state_bucket_name = "chess-puzzle-generator-tfstate-<account-id>"
lock_table_name   = "chess-puzzle-generator-terraform-locks"
deploy_role_arn   = "arn:aws:iam::<account-id>:role/chess-puzzle-generator-github-deploy"

backend_hcl = <<EOT
  bucket         = "chess-puzzle-generator-tfstate-<account-id>"
  key            = "chess-puzzle-generator/terraform.tfstate"
  region         = "eu-north-1"
  dynamodb_table = "chess-puzzle-generator-terraform-locks"
  encrypt        = true
EOT
```

### 1.5 — Create `terraform/backend.hcl`

Copy the `backend_hcl` output into a new file at `terraform/backend.hcl`. This file is gitignored and only used when running Terraform locally.

```bash
# terraform/backend.hcl
bucket         = "chess-puzzle-generator-tfstate-<account-id>"
key            = "chess-puzzle-generator/terraform.tfstate"
region         = "eu-north-1"
dynamodb_table = "chess-puzzle-generator-terraform-locks"
encrypt        = true
```

---

## Step 2 — Configure GitHub Secrets and Variables

The CD workflow reads secrets and variables from a GitHub Actions **`production` environment**. Go to your repository on GitHub:

`Settings → Environments → New environment → production`

Then add the following.

### Secrets

> Secrets are encrypted and never visible after saving. Generate the values as instructed below.

| Secret | How to generate | Description |
|---|---|---|
| `AWS_DEPLOY_ROLE_ARN` | From bootstrap output `deploy_role_arn` | IAM role GitHub Actions assumes via OIDC |
| `TF_STATE_BUCKET` | From bootstrap output `state_bucket_name` | S3 bucket for Terraform state |
| `TF_LOCK_TABLE` | From bootstrap output `lock_table_name` | DynamoDB table for state locking |
| `S3_BUCKET_NAME` | Choose a globally unique name e.g. `chess-puzzle-generator-games-<account-id>` | Temporary game storage bucket |
| `LAMBDA_SECRET` | `python3 -c "import secrets; print(secrets.token_hex(32))"` | Shared secret for Lambda → EC2 callbacks |
| `DB_PASSWORD` | Any strong password | PostgreSQL password injected via SSM |

### Variables

> Variables are plain text and visible in logs.

| Variable | Value | Description |
|---|---|---|
| `AWS_REGION` | `eu-north-1` | AWS region for all resources |
| `PROJECT_NAME` | `chess-puzzle-generator` | Prefix for all resource names |
| `EC2_INSTANCE_TYPE` | `t3.small` | EC2 instance type |
| `APP_REPO_URL` | `https://github.com/<your-username>/chess-puzzle-generator.git` | Repo cloned onto EC2 at boot |

---

## Step 3 — Trigger the First Deployment

With bootstrap complete and GitHub configured, push any change to `main` to trigger the pipeline.

```bash
git add .
git commit -m "chore: trigger initial cloud deployment"
git push origin main
```

The pipeline runs in two sequential workflows.

---

## CI/CD Pipeline

### CI Workflow (`.github/workflows/ci.yml`)

Runs on every push and pull request to `main`.

| Job | What it does |
|---|---|
| `backend` | Installs Python deps, spins up a PostgreSQL service container, runs the full test suite with coverage |
| `lambda` | Runs ETL and puzzle generator Lambda unit tests with mocked AWS |
| `terraform-validate` | Runs `terraform fmt -check` and `terraform validate` (no backend needed) |

All three jobs must pass before the deploy workflow is triggered.

### CD Workflow (`.github/workflows/deploy.yml`)

Triggered automatically when CI passes on `main`. Runs in the `production` environment.

```
① Checkout code at the exact SHA that passed CI
② Configure AWS credentials via OIDC (no static keys)
③ Terraform init with S3 backend
④ Targeted apply — create ECR repository if it doesn't exist yet
⑤ Log in to ECR
⑥ Build and push puzzle generator Docker image (linux/amd64)
⑦ Build ETL Lambda zip (pip install + handler.py)
⑧ Full terraform apply — provision / update all AWS resources
```

> **OIDC authentication** — GitHub Actions assumes the deploy IAM role using a short-lived token. No AWS access keys are stored anywhere.

---

## What Gets Deployed

`terraform apply` provisions the following resources on every deploy:

### Compute

| Resource | Details |
|---|---|
| EC2 instance | `t3.small`, Amazon Linux 2023, runs Docker Compose stack |
| Elastic IP | Stable public IP that survives instance stop/start |
| Security group | Port 80 (Nginx) and 8000 (FastAPI / Lambda callbacks) open |

### Serverless

| Resource | Details |
|---|---|
| ETL Lambda | Python 3.12, deployed as a zip, 512 MB, 5-minute timeout |
| Puzzle Generator Lambda | Container image from ECR, 3 GB, 15-minute timeout, Stockfish bundled |

### Storage & Config

| Resource | Details |
|---|---|
| S3 bucket (games) | Private, 1-day object expiry lifecycle rule |
| SSM Parameter Store | `db_password` and `lambda_secret` (SecureString), `lambda_etl_arn` (String) |
| ECR repository | Stores puzzle generator image; keeps latest 5 images |

### IAM

| Role | Purpose |
|---|---|
| `chess-puzzle-generator-ec2` | Allows EC2 to invoke ETL Lambda and read SSM parameters |
| `chess-puzzle-generator-etl-lambda` | Allows ETL Lambda to write to S3 and invoke puzzle generator |
| `chess-puzzle-generator-puzzles-lambda` | Allows puzzle generator to read and delete from S3 |

---

## EC2 Self-Configuration

The EC2 instance configures itself completely on first boot via `user_data.sh` — no manual SSH or SSM commands required. The script:

1. Installs Docker, Docker Compose, and Docker Buildx
2. Clones the application repository
3. Fetches secrets from SSM Parameter Store (`db_password`, `lambda_secret`)
4. Retries fetching `lambda_etl_arn` from SSM until it appears (resolves a dependency cycle where the ETL Lambda needs the EC2 Elastic IP to configure its callback URL)
5. Writes `.env` to `/home/ec2-user/app/.env`
6. Starts the Docker Compose stack (`docker compose up -d`)

> The retry loop for `lambda_etl_arn` runs up to 10 times with a 30-second delay between attempts (~5 minutes maximum wait).

---

## Verifying the Deployment

After `terraform apply` completes, retrieve the EC2 public IP from the Terraform outputs:

```bash
cd terraform
terraform output ec2_public_ip
```

### Check the application

```bash
# Health endpoint
curl http://<ec2-public-ip>:8000/health
# Expected: {"status":"healthy"}

# Root endpoint
curl http://<ec2-public-ip>/
```

Or open `http://<ec2-public-ip>` in your browser to access the puzzle UI.

### Check user_data completed successfully

```bash
# Connect via SSM (no SSH key needed)
aws ssm start-session --target <instance-id> --region eu-north-1

# Inside the session — check cloud-init log
sudo cat /var/log/cloud-init-output.log | tail -50

# Verify all containers are running
sudo -u ec2-user docker compose -f /home/ec2-user/app/docker-compose.yml ps
```

All five containers (`postgres`, `redis`, `backend`, `worker`, `nginx`) should show as running.

---

## Accessing the EC2 Instance

Connect to the EC2 instance without an SSH key using AWS Systems Manager Session Manager:

```bash
aws ssm start-session \
  --target <instance-id> \
  --region eu-north-1
```

Or copy the pre-built command from Terraform outputs:

```bash
cd terraform
terraform output ssm_connect_command
```

---

## Worker Mode

The application supports two worker modes controlled by the `WORKER_MODE` environment variable.

| Mode | How it works | When to use |
|---|---|---|
| `local` | A Docker container runs Stockfish locally, processes jobs from a Redis queue | Local development |
| `lambda` | FastAPI invokes the ETL Lambda via `boto3`; Lambda callbacks results back to EC2 | Cloud deployment |

In production (cloud), `WORKER_MODE=lambda` is set automatically by `user_data.sh` via the SSM-injected `.env`.

---

## Tearing Down

To destroy all AWS resources created by the main Terraform configuration:

```bash
cd terraform
terraform destroy
```

To also remove the bootstrap resources (state bucket, lock table, OIDC provider, deploy role):

```bash
cd bootstrap
terraform destroy
```

> **Warning** — Destroying the bootstrap S3 bucket will delete all Terraform state. Do this only when you are fully decommissioning the project.
