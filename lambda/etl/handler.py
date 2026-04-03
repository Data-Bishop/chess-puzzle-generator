"""
ETL Lambda: fetches Chess.com games, stores in S3, triggers puzzle generator Lambda.

Environment variables (set by Terraform):
    EC2_API_URL        — Base URL of the FastAPI backend on EC2 (e.g. http://1.2.3.4:8000)
    LAMBDA_SECRET      — Shared secret for EC2 callback authentication
    S3_BUCKET_NAME     — S3 bucket for temporary game storage
    LAMBDA_PUZZLES_ARN — ARN of the Puzzle Generator Lambda to invoke
"""
import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import boto3
import httpx

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

EC2_API_URL = os.environ["EC2_API_URL"]
LAMBDA_SECRET = os.environ["LAMBDA_SECRET"]
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
LAMBDA_PUZZLES_ARN = os.environ["LAMBDA_PUZZLES_ARN"]

MAX_GAMES_TO_SAMPLE = 100
CHESS_COM_BASE = "https://api.chess.com/pub"
HTTP_HEADERS = {"User-Agent": "Chess Puzzle Generator (Educational Project)"}

s3 = boto3.client("s3")
lambda_client = boto3.client("lambda")


def handler(event, context):
    """
    Lambda entry point.

    Expected event shape:
    {
        "job_id":       "<uuid>",
        "username":     "hikaru",
        "time_control": "blitz",      # optional
        "date_from":    "2024-01-01", # optional ISO date string
        "date_to":      "2024-03-31"  # optional ISO date string
    }
    """
    job_id = event["job_id"]
    username = event["username"]
    time_control = event.get("time_control")
    date_from = event.get("date_from")
    date_to = event.get("date_to")

    try:
        _update_status(job_id, "processing")

        games = _fetch_games(username, time_control, date_from, date_to)

        if not games:
            _update_status(job_id, "failed", error_message="No games found for this user with the given filters")
            return {"statusCode": 200}

        # Cap the number of games to keep analysis time reasonable
        if len(games) > MAX_GAMES_TO_SAMPLE:
            games = random.sample(games, MAX_GAMES_TO_SAMPLE)
            logger.info("Sampled %d games from total fetched", MAX_GAMES_TO_SAMPLE)

        # Store game data in S3 (auto-deleted after 1 hour via lifecycle rule)
        s3_key = f"{job_id}/games.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(games),
            ContentType="application/json",
        )
        logger.info("Stored %d games in s3://%s/%s", len(games), S3_BUCKET, s3_key)

        # Tell the EC2 API that we're now generating puzzles
        _update_status(job_id, "generating_puzzles", total_games=len(games))

        # Invoke the Puzzle Generator Lambda asynchronously
        lambda_client.invoke(
            FunctionName=LAMBDA_PUZZLES_ARN,
            InvocationType="Event",  # fire-and-forget
            Payload=json.dumps({
                "job_id": job_id,
                "s3_bucket": S3_BUCKET,
                "s3_key": s3_key,
                "total_games": len(games),
            }),
        )
        logger.info("Invoked puzzle generator Lambda for job %s", job_id)

        return {"statusCode": 200, "body": json.dumps({"ok": True, "games": len(games)})}

    except ValueError as e:
        # User not found or invalid input
        _update_status(job_id, "failed", error_message=str(e))
        return {"statusCode": 200}
    except Exception as e:
        logger.error("Unhandled error for job %s: %s", job_id, e)
        _update_status(job_id, "failed", error_message=f"ETL error: {str(e)}")
        raise


# Chess.com API helpers
def _fetch_games(
    username: str,
    time_control: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> List[Dict[str, Any]]:
    """Fetch games from Chess.com, applying date and time-control filters."""
    with httpx.Client(timeout=30, follow_redirects=True, headers=HTTP_HEADERS) as client:
        # Step 1: get list of monthly archive URLs
        resp = client.get(f"{CHESS_COM_BASE}/player/{username}/games/archives")
        if resp.status_code == 404:
            raise ValueError(f"Player '{username}' not found on Chess.com")
        resp.raise_for_status()
        archives = resp.json().get("archives", [])

        if not archives:
            return []

        # Step 2: filter archives by date range (or default to last 3 months)
        if date_from or date_to:
            df = datetime.fromisoformat(date_from) if date_from else None
            dt = datetime.fromisoformat(date_to) if date_to else None
            archives = _filter_archives_by_date(archives, df, dt)
        else:
            archives = archives[-3:]

        # Step 3: fetch games from each archive
        all_games: List[Dict[str, Any]] = []
        for archive_url in archives:
            try:
                resp = client.get(archive_url)
                resp.raise_for_status()
                games = resp.json().get("games", [])

                if time_control:
                    games = [
                        g for g in games
                        if g.get("time_class", "").lower() == time_control.lower()
                    ]

                all_games.extend(games)
                time.sleep(0.1)  # courtesy delay for Chess.com API
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", archive_url, e)
                continue

        return all_games


def _filter_archives_by_date(
    archives: List[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> List[str]:
    """Return only archives whose year/month falls within [date_from, date_to]."""
    filtered = []
    for url in archives:
        parts = url.rstrip("/").split("/")
        try:
            year, month = int(parts[-2]), int(parts[-1])
            archive_date = datetime(year, month, 1)

            if date_from and archive_date < datetime(date_from.year, date_from.month, 1):
                continue
            if date_to and archive_date > datetime(date_to.year, date_to.month, 1):
                continue

            filtered.append(url)
        except (ValueError, IndexError):
            continue
    return filtered


# EC2 API callback helper
def _update_status(
    job_id: str,
    status: str,
    total_games: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """POST a status update to the EC2 FastAPI backend."""
    payload: Dict[str, Any] = {"status": status}
    if total_games is not None:
        payload["total_games"] = total_games
    if error_message:
        payload["error_message"] = error_message

    try:
        with httpx.Client(timeout=10) as client:
            client.post(
                f"{EC2_API_URL}/jobs/{job_id}/status",
                json=payload,
                headers={"Authorization": f"Bearer {LAMBDA_SECRET}"},
            )
    except Exception as e:
        # Don't let a callback failure crash the Lambda
        logger.warning("Failed to update job status to '%s': %s", status, e)
