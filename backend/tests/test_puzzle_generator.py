"""Tests for PuzzleGenerator — pure-logic methods only (no Stockfish required)."""
import chess
import pytest
from unittest.mock import MagicMock, patch, call

from puzzle_generator import Puzzle, PuzzleGenerator


@pytest.fixture()
def gen():
    """PuzzleGenerator with the engine stubbed out (never started)."""
    g = PuzzleGenerator(stockfish_path="/dev/null")
    g.engine = None
    return g


# _piece_value
class TestPieceValue:
    def test_pawn(self, gen):
        assert gen._piece_value(chess.Piece(chess.PAWN, chess.WHITE)) == 1

    def test_knight(self, gen):
        assert gen._piece_value(chess.Piece(chess.KNIGHT, chess.WHITE)) == 3

    def test_bishop(self, gen):
        assert gen._piece_value(chess.Piece(chess.BISHOP, chess.BLACK)) == 3

    def test_rook(self, gen):
        assert gen._piece_value(chess.Piece(chess.ROOK, chess.WHITE)) == 5

    def test_queen(self, gen):
        assert gen._piece_value(chess.Piece(chess.QUEEN, chess.BLACK)) == 9

    def test_king(self, gen):
        assert gen._piece_value(chess.Piece(chess.KING, chess.WHITE)) == 0


# _estimate_rating
class TestEstimateRating:
    def test_base_rating_two_move_solution(self, gen):
        # swing 300 (neither branch) + (2-2)*100 = 1200
        rating = gen._estimate_rating(eval_swing=300, solution_length=2)
        assert rating == 1200

    def test_large_swing_lowers_rating(self, gen):
        # swing > 500 → -100 → 1100
        rating = gen._estimate_rating(eval_swing=600, solution_length=2)
        assert rating == 1100

    def test_small_swing_raises_rating(self, gen):
        # swing < 250 → +150 → 1350
        rating = gen._estimate_rating(eval_swing=200, solution_length=2)
        assert rating == 1350

    def test_longer_solution_raises_rating(self, gen):
        # swing 300, length 4 → 1200 + (4-2)*100 = 1400
        rating = gen._estimate_rating(eval_swing=300, solution_length=4)
        assert rating == 1400

    def test_rating_floor_with_large_swing_and_short_solution(self, gen):
        # swing > 500 → -100; (1-2)*100 = -100; 1200 - 100 - 100 = 1000 (above 800)
        # The 800 floor is only reachable for hypothetical negative solution lengths.
        rating = gen._estimate_rating(eval_swing=9999, solution_length=1)
        assert rating == 1000

    def test_rating_clamped_at_2500(self, gen):
        rating = gen._estimate_rating(eval_swing=100, solution_length=25)
        assert rating == 2500


# _detect_theme
class TestDetectTheme:
    def test_promotion(self, gen):
        """Pawn promotion move → 'promotion'."""
        # White pawn on e7, black king far away; play e7e8=Q
        board = chess.Board("8/4P3/8/8/8/8/8/k6K w - - 0 1")
        move = chess.Move.from_uci("e7e8q")
        assert gen._detect_theme(board, move) == "promotion"

    def test_fork_knight(self, gen):
        """Knight fork on two rooks → 'fork'."""
        # White knight on e5 attacks c6 (black rook) and g6 (black rook)
        # Position: Nc5 attacks b7 (queen) and d7 (rook)
        # Build a position where knight move creates fork
        board = chess.Board("8/1q1r4/8/2N5/8/8/8/k6K w - - 0 1")
        # Ne5 attacks b7 (queen) and d7 (rook); but it's already on c5
        # Nc5 attacks a6, b7, d7, e6, e4, d3, b3, a4
        # Move knight from e3 to c4 to fork queen on b6 and rook on d6
        # Let's use a cleaner setup: knight moves to a square that attacks two rooks
        board2 = chess.Board("3r4/8/3r4/4N3/8/8/8/k6K w - - 0 1")
        # Ne5 attacks d7, f7, c6, g6, c4, g4, d3, f3
        # Move Ne5 to f7 to attack rook on d8 and rook on d6
        move2 = chess.Move.from_uci("e5f7")
        theme = gen._detect_theme(board2, move2)
        # f7 attacks d8 (rook) and d6 (rook) and h8 — two rooks → fork
        assert theme == "fork"

    def test_check(self, gen):
        """Move that gives check → 'check' (or fork if it also forks)."""
        # Queen gives check
        board = chess.Board("4k3/8/8/8/8/8/8/4K2Q w - - 0 1")
        move = chess.Move.from_uci("h1h8")  # Qh8+ check
        theme = gen._detect_theme(board, move)
        assert theme in ("check", "fork")

    def test_winning_material_capture(self, gen):
        """Pawn captures queen → 'winning_material'."""
        board = chess.Board("8/4k3/8/4q3/3P4/8/8/4K3 w - - 0 1")
        move = chess.Move.from_uci("d4e5")  # pawn captures queen
        theme = gen._detect_theme(board, move)
        assert theme == "winning_material"

    def test_generic_tactic_fallback(self, gen):
        """Quiet move that isn't a capture, check, or fork → 'tactic'."""
        # Rook on a1 moves to a2; black king on g8 — no check, no capture, no fork
        board = chess.Board("6k1/8/8/8/8/8/8/R3K3 w Q - 0 1")
        move = chess.Move.from_uci("a1a2")
        theme = gen._detect_theme(board, move)
        assert theme == "tactic"

    def test_no_piece_on_square_returns_tactic(self, gen):
        """If move.from_square has no piece, gracefully return 'tactic'."""
        board = chess.Board("8/4k3/8/8/8/8/8/4K3 w - - 0 1")
        # Construct a move from an empty square
        move = chess.Move(chess.E3, chess.E4)
        assert gen._detect_theme(board, move) == "tactic"


# _is_fork
class TestIsFork:
    def test_knight_forking_queen_and_rook(self, gen):
        # Knight on f7 attacks d8 (rook) and d6 (rook)
        board = chess.Board("3r4/5N2/3r4/8/8/8/8/k6K w - - 0 1")
        assert gen._is_fork(board, chess.F7) is True

    def test_not_a_fork_only_one_target(self, gen):
        board = chess.Board("3r4/5N2/8/8/8/8/8/k6K w - - 0 1")
        # Knight on f7 attacks d8 (rook) and d6 (empty) etc.
        # Only one valuable target (d8 rook)
        assert gen._is_fork(board, chess.F7) is False

    def test_no_piece_on_square_returns_false(self, gen):
        board = chess.Board("8/8/8/8/8/8/8/k6K w - - 0 1")
        assert gen._is_fork(board, chess.E4) is False


# generate_puzzles_from_pgn (engine mocked)
OPERA_GAME_PGN = """\
[Event "Paris"]
[Site "Paris"]
[Date "1858.??.??"]
[White "Morphy, Paul"]
[Black "Duke Karl / Count Isouard"]
[Result "1-0"]

1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6 7. Qb3 Qe7
8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7 12. O-O-O Rd8 13. Rxd7 Rxd7
14. Rd1 Qe6 15. Bxd7+ Nxd7 16. Qb8+ Nxb8 17. Rd8# 1-0
"""


class TestGeneratePuzzlesFromPgn:
    def test_empty_pgn_returns_no_puzzles(self, gen):
        gen._start_engine = MagicMock()
        gen._evaluate_position = MagicMock(return_value=0)
        assert gen.generate_puzzles_from_pgn("") == []

    def test_large_eval_swing_triggers_puzzle_creation(self, gen):
        """When eval swings by ≥200 cp a puzzle should be attempted."""
        created_puzzle = Puzzle(
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            solution=["e7e5", "d2d4"],
            theme="tactic",
            rating=1200,
            game_url=None,
        )

        gen._start_engine = MagicMock()
        # Return a sequence: first 9 moves return 0 (skipped as opening),
        # then alternate 0 / 300 to trigger a swing on move 10+.
        eval_values = [0] * 9 + [0, 300] + [300] * 50
        gen._evaluate_position = MagicMock(side_effect=eval_values)
        gen._create_puzzle = MagicMock(return_value=created_puzzle)

        puzzles = gen.generate_puzzles_from_pgn(OPERA_GAME_PGN, max_puzzles=1)

        assert len(puzzles) == 1
        assert puzzles[0].theme == "tactic"
        gen._create_puzzle.assert_called_once()

    def test_max_puzzles_cap_respected(self, gen):
        created_puzzle = Puzzle(
            fen="8/8/8/8/8/8/8/8 w - - 0 1",
            solution=["e2e4"],
            theme="tactic",
            rating=1200,
            game_url=None,
        )
        gen._start_engine = MagicMock()
        gen._evaluate_position = MagicMock(side_effect=[0] * 9 + [0, 300] * 30)
        gen._create_puzzle = MagicMock(return_value=created_puzzle)

        puzzles = gen.generate_puzzles_from_pgn(OPERA_GAME_PGN, max_puzzles=1)

        assert len(puzzles) <= 1

    def test_no_swing_produces_no_puzzles(self, gen):
        gen._start_engine = MagicMock()
        gen._evaluate_position = MagicMock(return_value=0)  # flat eval throughout
        gen._create_puzzle = MagicMock()

        puzzles = gen.generate_puzzles_from_pgn(OPERA_GAME_PGN, max_puzzles=5)

        assert puzzles == []
        gen._create_puzzle.assert_not_called()


# generate_puzzles_from_games
class TestGeneratePuzzlesFromGames:
    def _make_puzzle(self, theme="tactic"):
        return Puzzle(
            fen="8/8/8/8/8/8/8/8 w - - 0 1",
            solution=["e2e4"],
            theme=theme,
            rating=1200,
            game_url=None,
        )

    def test_skips_games_without_pgn(self, gen):
        gen._start_engine = MagicMock()
        gen._stop_engine = MagicMock()
        games = [{"url": "https://chess.com/game/1"}]  # no pgn key
        puzzles = gen.generate_puzzles_from_games(games)
        assert puzzles == []

    def test_total_puzzle_cap_enforced(self, gen):
        gen._start_engine = MagicMock()
        gen._stop_engine = MagicMock()
        per_game_puzzles = [self._make_puzzle(), self._make_puzzle()]

        with patch.object(gen, "generate_puzzles_from_pgn", return_value=per_game_puzzles):
            games = [{"pgn": "dummy"} for _ in range(20)]
            puzzles = gen.generate_puzzles_from_games(games, max_total_puzzles=5)

        assert len(puzzles) == 5

    def test_stop_engine_called_even_on_exception(self, gen):
        gen._start_engine = MagicMock()
        gen._stop_engine = MagicMock()

        with patch.object(gen, "generate_puzzles_from_pgn", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                gen.generate_puzzles_from_games([{"pgn": "x"}])

        gen._stop_engine.assert_called_once()
