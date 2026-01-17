"""FastAPI main application."""
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from database import get_db, engine, Base
from models import Job, Puzzle
from schemas import JobCreate, JobResponse, PuzzleResponse, PuzzleListResponse
from config import settings

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


@app.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(job_data: JobCreate, db: Session = Depends(get_db)):
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

    # TODO: In Phase 2, add job to Redis queue for processing

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
