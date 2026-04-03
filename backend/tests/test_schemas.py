"""Tests for Pydantic request/response schemas."""
import pytest
from pydantic import ValidationError
from datetime import datetime, timezone

from schemas import (
    JobCreate,
    LambdaStatusUpdate,
    LambdaPuzzleData,
    LambdaPuzzleIngest,
)


class TestJobCreate:
    def test_valid_minimal(self):
        job = JobCreate(username="hikaru")
        assert job.username == "hikaru"
        assert job.date_from is None
        assert job.date_to is None
        assert job.min_rating is None
        assert job.max_rating is None
        assert job.time_control is None

    def test_valid_with_all_filters(self):
        job = JobCreate(
            username="hikaru",
            date_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            date_to=datetime(2024, 3, 31, tzinfo=timezone.utc),
            min_rating=1000,
            max_rating=2000,
            time_control="blitz",
        )
        assert job.min_rating == 1000
        assert job.max_rating == 2000
        assert job.time_control == "blitz"

    def test_username_empty_string_rejected(self):
        with pytest.raises(ValidationError):
            JobCreate(username="")

    def test_username_too_long_rejected(self):
        with pytest.raises(ValidationError):
            JobCreate(username="x" * 256)

    def test_username_255_chars_accepted(self):
        job = JobCreate(username="x" * 255)
        assert len(job.username) == 255

    def test_min_rating_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            JobCreate(username="hikaru", min_rating=-1)

    def test_max_rating_above_3500_rejected(self):
        with pytest.raises(ValidationError):
            JobCreate(username="hikaru", max_rating=3501)

    def test_rating_boundary_values_accepted(self):
        job = JobCreate(username="hikaru", min_rating=0, max_rating=3500)
        assert job.min_rating == 0
        assert job.max_rating == 3500

    def test_time_control_too_long_rejected(self):
        with pytest.raises(ValidationError):
            JobCreate(username="hikaru", time_control="x" * 51)

    def test_missing_username_rejected(self):
        with pytest.raises(ValidationError):
            JobCreate()


class TestLambdaStatusUpdate:
    def test_valid_status_only(self):
        payload = LambdaStatusUpdate(status="processing")
        assert payload.status == "processing"
        assert payload.total_games is None
        assert payload.error_message is None

    def test_valid_with_all_fields(self):
        payload = LambdaStatusUpdate(
            status="generating_puzzles",
            total_games=100,
        )
        assert payload.total_games == 100

    def test_valid_failed_with_error(self):
        payload = LambdaStatusUpdate(
            status="failed",
            error_message="Player not found on Chess.com",
        )
        assert payload.error_message == "Player not found on Chess.com"

    def test_missing_status_rejected(self):
        with pytest.raises(ValidationError):
            LambdaStatusUpdate()


class TestLambdaPuzzleData:
    def test_valid_minimal(self):
        puzzle = LambdaPuzzleData(
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            solution=["e7e5", "d2d4"],
        )
        assert len(puzzle.solution) == 2
        assert puzzle.theme is None
        assert puzzle.rating is None

    def test_valid_with_all_fields(self):
        puzzle = LambdaPuzzleData(
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            solution=["e7e5"],
            theme="fork",
            rating=1500,
            game_url="https://www.chess.com/game/live/123",
        )
        assert puzzle.theme == "fork"
        assert puzzle.rating == 1500

    def test_missing_fen_rejected(self):
        with pytest.raises(ValidationError):
            LambdaPuzzleData(solution=["e7e5"])

    def test_missing_solution_rejected(self):
        with pytest.raises(ValidationError):
            LambdaPuzzleData(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def test_empty_solution_accepted(self):
        # Schema allows empty list — business logic enforces minimum length
        puzzle = LambdaPuzzleData(
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            solution=[],
        )
        assert puzzle.solution == []


class TestLambdaPuzzleIngest:
    def test_valid_with_puzzles(self):
        payload = LambdaPuzzleIngest(
            puzzles=[
                LambdaPuzzleData(
                    fen="6k1/6p1/4rq2/p4bNP/2P5/PP1r2R1/5PQK/8 b - - 1 42",
                    solution=["e6d6", "c4c5"],
                    theme="tactic",
                    rating=1800,
                )
            ],
            total_games=50,
        )
        assert len(payload.puzzles) == 1
        assert payload.total_games == 50

    def test_empty_puzzles_list_accepted(self):
        payload = LambdaPuzzleIngest(puzzles=[], total_games=10)
        assert payload.puzzles == []

    def test_missing_total_games_rejected(self):
        with pytest.raises(ValidationError):
            LambdaPuzzleIngest(puzzles=[])

    def test_missing_puzzles_rejected(self):
        with pytest.raises(ValidationError):
            LambdaPuzzleIngest(total_games=10)
