"""SQLAlchemy ORM models."""
from datetime import datetime, timedelta
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from database import Base


class Job(Base):
    """Job model for tracking puzzle generation requests."""

    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Optional filters (for later use)
    date_from = Column(DateTime, nullable=True)
    date_to = Column(DateTime, nullable=True)
    min_rating = Column(Integer, nullable=True)
    max_rating = Column(Integer, nullable=True)
    time_control = Column(String(50), nullable=True)

    # Metadata
    total_games = Column(Integer, default=0)
    total_puzzles = Column(Integer, default=0)

    # Relationship to puzzles
    puzzles = relationship("Puzzle", back_populates="job", cascade="all, delete-orphan")


class Puzzle(Base):
    """Puzzle model for storing generated chess puzzles."""

    __tablename__ = "puzzles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    fen = Column(String(255), nullable=False)
    solution = Column(JSON, nullable=False)  # Array of moves in UCI format
    theme = Column(String(100), nullable=True)  # e.g., "fork"
    rating = Column(Integer, nullable=True)  # Estimated puzzle difficulty
    game_url = Column(String(500), nullable=True)  # Link to original Chess.com game
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24), index=True)

    # Relationship to job
    job = relationship("Job", back_populates="puzzles")
