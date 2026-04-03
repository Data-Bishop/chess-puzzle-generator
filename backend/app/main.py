"""FastAPI main application."""
import json
import logging
from datetime import datetime, timedelta, timezone
import boto3
from fastapi import FastAPI, Depends, HTTPException, status, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from database import get_db, engine, Base
from models import Job, Puzzle
from schemas import (
    JobCreate, JobResponse, PuzzleResponse, PuzzleListResponse,
    LambdaStatusUpdate, LambdaPuzzleIngest,
)
from config import settings
from job_queue import queue
from rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(
    title="Chess Puzzle Generator API",
    description="Generate chess puzzles from Chess.com games",
    version="0.1.0",
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Note to SELF: In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    """Root endpoint."""
    return {
        "message": "Chess Puzzle Generator API",
        "version": "0.1.0",
        "status": "online",
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


def get_client_ip(request: Request) -> str:
    """Extract client IP address, handling proxies."""
    # Check X-Forwarded-For header (set by proxies/load balancers)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP in the chain (original client)
        return forwarded_for.split(",")[0].strip()
    # Fall back to direct client host
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request):
    """
    Dependency to check rate limit for job creation.

    Raises:
        HTTPException: 429 if rate limit exceeded
    """
    client_ip = get_client_ip(request)
    is_allowed, retry_after = rate_limiter.is_allowed(client_ip)

    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)}
        )


@app.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    job_data: JobCreate,
    db: Session = Depends(get_db),
    _: None = Depends(check_rate_limit)
):
    """
    Create a new puzzle generation job.

    Args:
        job_data: Job creation data with username and optional filters
        db: Database session

    Returns:
        JobResponse: Created job details
    """
    # Create new job
    new_job = Job(
        username=job_data.username,
        status="pending",
        date_from=job_data.date_from,
        date_to=job_data.date_to,
        min_rating=job_data.min_rating,
        max_rating=job_data.max_rating,
        time_control=job_data.time_control,
    )

    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    # Push job to Redis queue for worker processing
    queue_data = {
        "job_id": str(new_job.id),
        "username": new_job.username,
        "date_from": new_job.date_from.isoformat() if new_job.date_from else None,
        "date_to": new_job.date_to.isoformat() if new_job.date_to else None,
        "min_rating": new_job.min_rating,
        "max_rating": new_job.max_rating,
        "time_control": new_job.time_control,
    }

    if settings.worker_mode == "lambda":
        try:
            lambda_client = boto3.client("lambda", region_name=settings.aws_region)
            lambda_client.invoke(
                FunctionName=settings.lambda_etl_arn,
                InvocationType="Event",  # async — returns immediately
                Payload=json.dumps(queue_data).encode(),
            )
        except Exception as e:
            logger.warning("Failed to invoke ETL Lambda for job %s: %s", new_job.id, e)
    else:
        queue_success = queue.push(str(new_job.id), queue_data)
        if not queue_success:
            logger.warning("Failed to push job %s to queue", new_job.id)

    return new_job


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID, db: Session = Depends(get_db)):
    """
    Get job status and details.

    Args:
        job_id: UUID of the job
        db: Database session

    Returns:
        JobResponse: Job details

    Raises:
        HTTPException: 404 if job not found
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    return job


@app.get("/jobs/{job_id}/puzzles", response_model=PuzzleListResponse)
def get_job_puzzles(job_id: UUID, db: Session = Depends(get_db)):
    """
    Get all puzzles for a specific job.

    Args:
        job_id: UUID of the job
        db: Database session

    Returns:
        PuzzleListResponse: List of puzzles

    Raises:
        HTTPException: 404 if job not found
    """
    # Verify job exists
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    # Get all puzzles for this job
    puzzles = db.query(Puzzle).filter(Puzzle.job_id == job_id).all()

    return PuzzleListResponse(
        puzzles=puzzles,
        total=len(puzzles)
    )


@app.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: UUID, db: Session = Depends(get_db)):
    """
    Delete a job and its associated puzzles.

    Args:
        job_id: UUID of the job
        db: Database session

    Raises:
        HTTPException: 404 if job not found
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    db.delete(job)  # Cascades to puzzles due to relationship configuration
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


def verify_lambda_secret(authorization: str = Header(None)):
    """Dependency that validates the shared secret sent by Lambda callbacks."""
    expected = settings.lambda_secret
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Lambda secret not configured on server"
        )
    if authorization != f"Bearer {expected}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authorization token"
        )


@app.post("/jobs/{job_id}/status", status_code=status.HTTP_200_OK)
def update_job_status(
    job_id: UUID,
    payload: LambdaStatusUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(verify_lambda_secret),
):
    """
    Callback endpoint for Lambda to update job status.

    Called by the ETL Lambda when games are extracted, and by the
    Puzzle Generator Lambda when puzzles are ready or an error occurs.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")

    job.status = payload.status

    if payload.total_games is not None:
        job.total_games = payload.total_games

    if payload.error_message:
        job.error_message = payload.error_message

    if payload.status in ("completed", "failed"):
        job.completed_at = datetime.now(timezone.utc)

    db.commit()
    return {"ok": True}


@app.post("/jobs/{job_id}/puzzles/ingest", status_code=status.HTTP_201_CREATED)
def ingest_puzzles(
    job_id: UUID,
    payload: LambdaPuzzleIngest,
    db: Session = Depends(get_db),
    _: None = Depends(verify_lambda_secret),
):
    """
    Callback endpoint for Lambda to bulk-insert generated puzzles.

    Called by the Puzzle Generator Lambda once Stockfish analysis is done.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    new_puzzles = [
        Puzzle(
            job_id=job_id,
            fen=p.fen,
            solution=p.solution,
            theme=p.theme,
            rating=p.rating,
            game_url=p.game_url,
            expires_at=expires_at,
        )
        for p in payload.puzzles
    ]
    db.add_all(new_puzzles)

    job.total_games = payload.total_games
    job.total_puzzles = len(new_puzzles)
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)

    db.commit()
    return {"ok": True, "puzzles_stored": len(new_puzzles)}
