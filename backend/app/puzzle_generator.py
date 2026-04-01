"""Puzzle generator using Stockfish for position analysis."""
import os
import chess
import chess.pgn
import chess.engine
from io import StringIO
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class Puzzle:
    """Represents a chess puzzle."""
    fen: str
    solution: List[str]  # UCI moves
    theme: Optional[str]
    rating: Optional[int]
    game_url: Optional[str]


class PuzzleGenerator:
    """Generates chess puzzles from games using Stockfish analysis."""

    # Minimum centipawn swing to consider a position tactical
    MIN_EVAL_SWING = 200  # 2 pawns

    # Stockfish analysis depth for position scanning
    ANALYSIS_DEPTH = 12

    # Analysis time limit per position (seconds) - kept low for throughput
    TIME_LIMIT = 0.1

    def __init__(self, stockfish_path: Optional[str] = None):
        """
        Initialize puzzle generator.

        Args:
            stockfish_path: Path to Stockfish binary. Uses env var if not provided.
        """
        self.stockfish_path = stockfish_path or os.getenv(
            "STOCKFISH_PATH", "/usr/games/stockfish"
        )
        self.engine = None

    def _start_engine(self):
        """Start Stockfish engine."""
        if self.engine is None:
            self.engine = chess.engine.SimpleEngine.popen_uci(self.stockfish_path)
            # Configure engine for faster analysis
            self.engine.configure({"Threads": 1, "Hash": 64})

    def _stop_engine(self):
        """Stop Stockfish engine."""
        if self.engine:
            self.engine.quit()
            self.engine = None

    def generate_puzzles_from_pgn(
        self,
        pgn_string: str,
        game_url: Optional[str] = None,
        max_puzzles: int = 2
    ) -> List[Puzzle]:
        """
        Generate puzzles from a PGN game string.

        Args:
            pgn_string: PGN format game string
            game_url: Optional URL to original game
            max_puzzles: Maximum puzzles to generate from this game

        Returns:
            List of Puzzle objects
        """
        try:
            self._start_engine()

            # Parse PGN
            pgn_io = StringIO(pgn_string)
            game = chess.pgn.read_game(pgn_io)

            if not game:
                return []

            puzzles = []
            board = game.board()
            previous_eval = None
            move_number = 0

            # Analyze each position
            for node in game.mainline():
                move_number += 1
                move = node.move
                board.push(move)

                # Skip early moves (opening)
                if move_number < 10:
                    previous_eval = self._evaluate_position(board)
                    continue

                # Evaluate current position
                current_eval = self._evaluate_position(board)

                if previous_eval is not None and current_eval is not None:
                    # Check for eval swing (blunder/tactical opportunity)
                    eval_swing = abs(current_eval - previous_eval)

                    if eval_swing >= self.MIN_EVAL_SWING:
                        # Found a tactical position - create puzzle from BEFORE the move
                        puzzle_board = board.copy()
                        puzzle_board.pop()  # Go back one move

                        puzzle = self._create_puzzle(
                            puzzle_board,
                            current_eval,
                            previous_eval,
                            game_url
                        )

                        if puzzle:
                            puzzles.append(puzzle)

                            if len(puzzles) >= max_puzzles:
                                break

                previous_eval = current_eval

            return puzzles

        except Exception as e:
            print(f"Error generating puzzles: {e}")
            return []

    def generate_puzzles_from_games(
        self,
        games: List[Dict[str, Any]],
        max_puzzles_per_game: int = 2,
        max_total_puzzles: int = 20
    ) -> List[Puzzle]:
        """
        Generate puzzles from multiple Chess.com game objects.

        Args:
            games: List of Chess.com game dictionaries (with 'pgn' field)
            max_puzzles_per_game: Max puzzles per game
            max_total_puzzles: Max total puzzles to generate

        Returns:
            List of Puzzle objects
        """
        all_puzzles = []

        try:
            self._start_engine()

            for i, game in enumerate(games):
                if len(all_puzzles) >= max_total_puzzles:
                    break

                pgn = game.get("pgn")
                if not pgn:
                    continue

                game_url = game.get("url")

                puzzles = self.generate_puzzles_from_pgn(
                    pgn,
                    game_url=game_url,
                    max_puzzles=max_puzzles_per_game
                )

                remaining = max_total_puzzles - len(all_puzzles)
                all_puzzles.extend(puzzles[:remaining])

                if (i + 1) % 10 == 0:
                    print(f"  Analyzed {i + 1}/{len(games)} games, {len(all_puzzles)} puzzles so far")

        finally:
            self._stop_engine()

        return all_puzzles

    def _evaluate_position(self, board: chess.Board) -> Optional[int]:
        """
        Evaluate a position using Stockfish.

        Args:
            board: Chess board position

        Returns:
            Centipawn evaluation (positive = white winning) or None on error
        """
        try:
            result = self.engine.analyse(
                board,
                chess.engine.Limit(time=self.TIME_LIMIT, depth=self.ANALYSIS_DEPTH)
            )

            score = result.get("score")
            if score is None:
                return None

            # Get centipawn score from white's perspective
            cp_score = score.white()

            if cp_score.is_mate():
                # Convert mate to large centipawn value
                mate_in = cp_score.mate()
                return 10000 if mate_in > 0 else -10000

            return cp_score.score()

        except Exception as e:
            print(f"Error evaluating position: {e}")
            return None

    def _create_puzzle(
        self,
        board: chess.Board,
        eval_after: int,
        eval_before: int,
        game_url: Optional[str]
    ) -> Optional[Puzzle]:
        """
        Create a puzzle from a tactical position.

        Args:
            board: Position BEFORE the tactical move
            eval_after: Evaluation after the move was played
            eval_before: Evaluation before the move
            game_url: URL to original game

        Returns:
            Puzzle object or None if no good puzzle found
        """
        try:
            # Find the best move sequence (solution)
            result = self.engine.analyse(
                board,
                chess.engine.Limit(time=0.5, depth=15)
            )

            pv = result.get("pv", [])
            if len(pv) < 2:
                return None

            # Get solution moves (typically 2-4 moves)
            solution_moves = [move.uci() for move in pv[:4]]

            # Detect tactical theme
            theme = self._detect_theme(board, pv[0])

            # Estimate puzzle rating based on eval swing
            eval_swing = abs(eval_after - eval_before)
            rating = self._estimate_rating(eval_swing, len(pv))

            return Puzzle(
                fen=board.fen(),
                solution=solution_moves,
                theme=theme,
                rating=rating,
                game_url=game_url
            )

        except Exception as e:
            print(f"Error creating puzzle: {e}")
            return None

    def _detect_theme(self, board: chess.Board, move: chess.Move) -> str:
        """
        Detect the tactical theme of a move.

        Args:
            board: Position before the move
            move: The tactical move

        Returns:
            Theme string (e.g., "fork", "pin", "discovery")
        """
        # Make the move on a copy
        test_board = board.copy()
        piece = board.piece_at(move.from_square)

        if piece is None:
            return "tactic"

        # Check for captures
        is_capture = board.is_capture(move)

        # Check for check
        test_board.push(move)
        gives_check = test_board.is_check()

        # Check for promotion
        is_promotion = move.promotion is not None

        # Simple theme detection
        if is_promotion:
            return "promotion"

        if gives_check and is_capture:
            return "discovered_attack"

        if gives_check:
            # Check if it's a double attack (fork)
            if self._is_fork(test_board, move.to_square):
                return "fork"
            return "check"

        if is_capture:
            # Check if capturing a higher value piece
            captured = board.piece_at(move.to_square)
            if captured and self._piece_value(captured) > self._piece_value(piece):
                return "winning_material"
            return "capture"

        # Check for fork (attacking multiple pieces)
        if self._is_fork(test_board, move.to_square):
            return "fork"

        return "tactic"

    def _is_fork(self, board: chess.Board, square: chess.Square) -> bool:
        """Check if a piece on a square is attacking multiple valuable pieces."""
        piece = board.piece_at(square)
        if piece is None:
            return False

        attacks = board.attacks(square)
        valuable_targets = 0

        for target_square in attacks:
            target_piece = board.piece_at(target_square)
            if target_piece and target_piece.color != piece.color:
                # Count queens, rooks, and the king as valuable
                if target_piece.piece_type in [chess.QUEEN, chess.ROOK, chess.KING]:
                    valuable_targets += 1

        return valuable_targets >= 2

    def _piece_value(self, piece: chess.Piece) -> int:
        """Get standard piece value."""
        values = {
            chess.PAWN: 1,
            chess.KNIGHT: 3,
            chess.BISHOP: 3,
            chess.ROOK: 5,
            chess.QUEEN: 9,
            chess.KING: 0
        }
        return values.get(piece.piece_type, 0)

    def _estimate_rating(self, eval_swing: int, solution_length: int) -> int:
        """
        Estimate puzzle difficulty rating.

        Args:
            eval_swing: Centipawn difference
            solution_length: Number of moves in solution

        Returns:
            Estimated rating (800-2500)
        """
        # Base rating
        rating = 1200

        # Adjust based on eval swing (bigger swing = easier to spot)
        if eval_swing > 500:
            rating -= 100
        elif eval_swing < 250:
            rating += 150

        # Adjust based on solution length (longer = harder)
        rating += (solution_length - 2) * 100

        # Clamp to reasonable range
        return max(800, min(2500, rating))

    def close(self):
        """Close the Stockfish engine."""
        self._stop_engine()


# Test the puzzle generator
if __name__ == "__main__":
    # Sample PGN for testing - Opera Game (Morphy vs Duke/Count, 1858)
    test_pgn = """
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

    print("Testing Puzzle Generator...")
    generator = PuzzleGenerator()

    try:
        puzzles = generator.generate_puzzles_from_pgn(test_pgn, max_puzzles=3)
        print(f"\nFound {len(puzzles)} puzzles:")

        for i, puzzle in enumerate(puzzles, 1):
            print(f"\nPuzzle {i}:")
            print(f"  FEN: {puzzle.fen}")
            print(f"  Solution: {puzzle.solution}")
            print(f"  Theme: {puzzle.theme}")
            print(f"  Rating: {puzzle.rating}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        generator.close()
