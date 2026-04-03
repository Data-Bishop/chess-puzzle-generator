"""Pydantic schemas for request/response validation."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID


# Job Schemas
class JobCreate(BaseModel):
    """Schema for creating a new job."""
    username: str = Field(..., min_length=1, max_length=255, description="Chess.com username")
    date_from: Optional[datetime] = Field(None, description="Filter games from this date")
    date_to: Optional[datetime] = Field(None, description="Filter games to this date")
    min_rating: Optional[int] = Field(None, ge=0, le=3500, description="Minimum rating filter")
    max_rating: Optional[int] = Field(None, ge=0, le=3500, description="Maximum rating filter")
    time_control: Optional[str] = Field(None, max_length=50, description="Time control filter (e.g., 'blitz', 'rapid')")


class JobResponse(BaseModel):
    """Schema for job response."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]
    total_games: int
    total_puzzles: int


# Puzzle Schemas
class PuzzleResponse(BaseModel):
    """Schema for puzzle response."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    fen: str
    solution: List[str]  # Array of UCI moves
    theme: Optional[str]
    rating: Optional[int]
    game_url: Optional[str]
    created_at: datetime


class PuzzleListResponse(BaseModel):
    """Schema for list of puzzles."""
    puzzles: List[PuzzleResponse]
    total: int


# Lambda callback schemas
class LambdaStatusUpdate(BaseModel):
    """Payload Lambda sends to update job status."""
    status: str
    total_games: Optional[int] = None
    error_message: Optional[str] = None


class LambdaPuzzleData(BaseModel):
    """Single puzzle sent by Lambda."""
    fen: str
    solution: List[str]
    theme: Optional[str] = None
    rating: Optional[int] = None
    game_url: Optional[str] = None


class LambdaPuzzleIngest(BaseModel):
    """Payload Lambda sends when puzzle generation is complete."""
    puzzles: List[LambdaPuzzleData]
    total_games: int
