"""Tests for the Puzzle Generator Lambda handler."""
import json
import pytest
import respx
import httpx
import boto3
import chess
from moto import mock_aws
from unittest.mock import MagicMock, patch

import puzzles.handler as handler


# Fixtures
SAMPLE_GAMES = [
    {
        "pgn": "[Event '?']\n1. e4 e5 2. Nf3 Nc6 *",
        "url": "https://www.chess.com/game/live/1",
    },
    {
        "pgn": "[Event '?']\n1. d4 d5 *",
        "url": "https://www.chess.com/game/live/2",
    },
]

BASE_EVENT = {
    "job_id": "bbbbbbbb-0000-0000-0000-000000000002",
    "s3_bucket": "test-chess-bucket",
    "s3_key": "bbbbbbbb-0000-0000-0000-000000000002/games.json",
    "total_games": 2,
}


@pytest.fixture()
def s3_with_games():
    """Moto S3 bucket pre-loaded with the sample games JSON."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="eu-north-1")
        s3.create_bucket(
            Bucket="test-chess-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-north-1"},
        )
        s3.put_object(
            Bucket="test-chess-bucket",
            Key=BASE_EVENT["s3_key"],
            Body=json.dumps(SAMPLE_GAMES),
        )
        yield s3


def _ec2_router():
    router = respx.MockRouter(assert_all_called=False)
    router.post(
        url__regex=r"http://ec2-test:8000/jobs/.+/(status|puzzles/ingest)"
    ).mock(return_value=httpx.Response(201, json={"ok": True, "puzzles_stored": 0}))
    return router


def _mock_engine(puzzles_per_game=0):
    """Return a mock chess engine that yields the given number of puzzles per game."""
    engine = MagicMock()
    engine.quit = MagicMock()

    if puzzles_per_game == 0:
        # Flat eval — no puzzles generated
        score_mock = MagicMock()
        score_mock.white.return_value.is_mate.return_value = False
        score_mock.white.return_value.score.return_value = 0
        engine.analyse.return_value = {"score": score_mock, "pv": []}
    else:
        # Alternate between 0 and 300 to trigger eval swings after move 10
        call_count = [0]

        def analyse_side_effect(board, limit):
            call_count[0] += 1
            score_mock = MagicMock()
            score_mock.white.return_value.is_mate.return_value = False
            # Even calls return 0, odd calls return 300 — swing of 300 ≥ MIN_EVAL_SWING
            score_mock.white.return_value.score.return_value = (
                300 if call_count[0] % 2 == 0 else 0
            )
            pv = [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")]
            return {"score": score_mock, "pv": pv}

        engine.analyse.side_effect = analyse_side_effect

    return engine


# handler() — happy path
class TestHandlerHappyPath:
    def test_returns_200(self, s3_with_games):
        with _ec2_router(), \
                patch("puzzles.handler.chess.engine.SimpleEngine.popen_uci",
                      return_value=_mock_engine()):
            result = handler.handler(BASE_EVENT, {})
        assert result["statusCode"] == 200

    def test_posts_puzzles_to_ec2(self, s3_with_games):
        ingest_calls = []

        def capture(request):
            if "ingest" in str(request.url):
                ingest_calls.append(json.loads(request.content))
            return httpx.Response(201, json={"ok": True, "puzzles_stored": 0})

        router = respx.MockRouter(assert_all_called=False)
        router.post(
            url__regex=r"http://ec2-test:8000/jobs/.+/(status|puzzles/ingest)"
        ).mock(side_effect=capture)

        with router, patch("puzzles.handler.chess.engine.SimpleEngine.popen_uci",
                           return_value=_mock_engine()):
            handler.handler(BASE_EVENT, {})

        assert len(ingest_calls) == 1
        assert "puzzles" in ingest_calls[0]
        assert ingest_calls[0]["total_games"] == BASE_EVENT["total_games"]

    def test_engine_quit_called_after_run(self, s3_with_games):
        engine = _mock_engine()
        with _ec2_router(), \
                patch("puzzles.handler.chess.engine.SimpleEngine.popen_uci",
                      return_value=engine):
            handler.handler(BASE_EVENT, {})
        engine.quit.assert_called_once()


# handler() — error path
class TestHandlerErrorPath:
    def test_raises_on_unhandled_exception(self, s3_with_games):
        with _ec2_router(), \
                patch("puzzles.handler.chess.engine.SimpleEngine.popen_uci",
                      side_effect=OSError("stockfish not found")):
            with pytest.raises(OSError):
                handler.handler(BASE_EVENT, {})

    def test_sends_failed_status_on_error(self, s3_with_games):
        statuses = []

        def capture(request):
            if "status" in str(request.url):
                statuses.append(json.loads(request.content)["status"])
            return httpx.Response(200)

        router = respx.MockRouter(assert_all_called=False)
        router.post(
            url__regex=r"http://ec2-test:8000/jobs/.+/(status|puzzles/ingest)"
        ).mock(side_effect=capture)

        with router, \
                patch("puzzles.handler.chess.engine.SimpleEngine.popen_uci",
                      side_effect=OSError("stockfish not found")):
            with pytest.raises(OSError):
                handler.handler(BASE_EVENT, {})

        assert "failed" in statuses


# _generate_puzzles
class TestGeneratePuzzles:
    def test_skips_games_without_pgn(self):
        engine = _mock_engine()
        games = [{"url": "https://chess.com/1"}]  # no pgn key
        with patch("puzzles.handler.chess.engine.SimpleEngine.popen_uci",
                   return_value=engine):
            result = handler._generate_puzzles(games)
        assert result == []
        engine.quit.assert_called_once()

    def test_respects_max_total_puzzles_cap(self):
        engine = _mock_engine(puzzles_per_game=2)
        many_games = [{"pgn": "[Event '?']\n" + " ".join(
            f"{i}. e4 e5" for i in range(1, 20)
        ) + " *", "url": None} for _ in range(30)]

        with patch("puzzles.handler.chess.engine.SimpleEngine.popen_uci",
                   return_value=engine):
            result = handler._generate_puzzles(many_games)

        assert len(result) <= handler.MAX_TOTAL_PUZZLES

    def test_engine_quit_called_even_on_exception(self):
        engine = MagicMock()
        engine.quit = MagicMock()
        engine.analyse.side_effect = RuntimeError("engine crash")

        games = [{"pgn": "[Event '?']\n1. e4 e5 *", "url": None}]

        with patch("puzzles.handler.chess.engine.SimpleEngine.popen_uci",
                   return_value=engine):
            handler._generate_puzzles(games)  # errors inside are caught per-game

        engine.quit.assert_called_once()


# Pure-logic helpers (no engine required)
class TestPieceValue:
    def test_pawn(self):
        assert handler._piece_value(chess.Piece(chess.PAWN, chess.WHITE)) == 1

    def test_queen(self):
        assert handler._piece_value(chess.Piece(chess.QUEEN, chess.BLACK)) == 9

    def test_king(self):
        assert handler._piece_value(chess.Piece(chess.KING, chess.WHITE)) == 0


class TestEstimateRating:
    def test_base_rating(self):
        assert handler._estimate_rating(300, 2) == 1200

    def test_large_swing_lowers_rating(self):
        assert handler._estimate_rating(600, 2) == 1100

    def test_small_swing_raises_rating(self):
        assert handler._estimate_rating(200, 2) == 1350

    def test_longer_solution_raises_rating(self):
        assert handler._estimate_rating(300, 4) == 1400

    def test_clamped_at_2500(self):
        assert handler._estimate_rating(100, 25) == 2500


class TestDetectTheme:
    def test_promotion(self):
        board = chess.Board("8/4P3/8/8/8/8/8/k6K w - - 0 1")
        assert handler._detect_theme(board, chess.Move.from_uci("e7e8q")) == "promotion"

    def test_winning_material_capture(self):
        board = chess.Board("8/4k3/8/4q3/3P4/8/8/4K3 w - - 0 1")
        assert handler._detect_theme(board, chess.Move.from_uci("d4e5")) == "winning_material"

    def test_no_piece_returns_tactic(self):
        board = chess.Board("8/4k3/8/8/8/8/8/4K3 w - - 0 1")
        assert handler._detect_theme(board, chess.Move(chess.E3, chess.E4)) == "tactic"


class TestIsFork:
    def test_knight_forking_two_rooks(self):
        board = chess.Board("3r4/5N2/3r4/8/8/8/8/k6K w - - 0 1")
        assert handler._is_fork(board, chess.F7) is True

    def test_single_target_not_a_fork(self):
        board = chess.Board("3r4/5N2/8/8/8/8/8/k6K w - - 0 1")
        assert handler._is_fork(board, chess.F7) is False

    def test_empty_square_returns_false(self):
        board = chess.Board("8/8/8/8/8/8/8/k6K w - - 0 1")
        assert handler._is_fork(board, chess.E4) is False


# _ingest_puzzles — auth header
class TestIngestPuzzles:
    @respx.mock
    def test_sends_correct_bearer_token(self):
        received = {}

        def capture(request):
            received["auth"] = request.headers.get("authorization")
            return httpx.Response(201, json={"ok": True})

        respx.post("http://ec2-test:8000/jobs/job-2/puzzles/ingest").mock(
            side_effect=capture
        )
        handler._ingest_puzzles("job-2", [], total_games=5)
        assert received["auth"] == "Bearer test-secret"

    @respx.mock
    def test_raises_on_http_error(self):
        respx.post("http://ec2-test:8000/jobs/job-2/puzzles/ingest").mock(
            return_value=httpx.Response(500)
        )
        with pytest.raises(httpx.HTTPStatusError):
            handler._ingest_puzzles("job-2", [], total_games=5)


# _update_status — error suppression
class TestUpdateStatus:
    @respx.mock
    def test_does_not_raise_on_network_error(self):
        respx.post("http://ec2-test:8000/jobs/job-2/status").mock(
            side_effect=httpx.ConnectError("down")
        )
        handler._update_status("job-2", "failed", error_message="boom")
