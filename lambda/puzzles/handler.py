"""
Puzzle Generator Lambda: loads games from S3, runs Stockfish analysis,
posts generated puzzles back to the EC2 FastAPI backend.

Environment variables (set by Terraform):
    EC2_API_URL    — Base URL of the FastAPI backend on EC2 (e.g. http://1.2.3.4:8000)
    LAMBDA_SECRET  — Shared secret for EC2 callback authentication
    STOCKFISH_PATH — Path to Stockfish binary inside the container (default: /usr/local/bin/stockfish)
"""
import json
import logging
import os
from io import StringIO
from typing import Any, Dict, List, Optional

import boto3
import chess
import chess.engine
import chess.pgn
import httpx

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

EC2_API_URL = os.environ["EC2_API_URL"]
LAMBDA_SECRET = os.environ["LAMBDA_SECRET"]
STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/usr/local/bin/stockfish")

# Analysis parameters — kept conservative to fit within Lambda timeout
MIN_EVAL_SWING = 200   # centipawns
ANALYSIS_DEPTH = 12
TIME_LIMIT = 0.1       # seconds per position
SOLUTION_DEPTH = 15
SOLUTION_TIME = 0.5    # seconds for PV search

MAX_PUZZLES_PER_GAME = 2
MAX_TOTAL_PUZZLES = 20

s3 = boto3.client("s3")


def handler(event, context):
    """
    Lambda entry point.

    Expected event shape (sent by ETL Lambda):
    {
        "job_id":       "<uuid>",
        "s3_bucket":    "chess-puzzle-generator-games",
        "s3_key":       "<job_id>/games.json",
        "total_games":  100
    }
    """
    job_id = event["job_id"]
    s3_bucket = event["s3_bucket"]
    s3_key = event["s3_key"]
    total_games = event["total_games"]

    try:
        # Load games from S3
        logger.info("Loading games from s3://%s/%s", s3_bucket, s3_key)
        obj = s3.get_object(Bucket=s3_bucket, Key=s3_key)
        games: List[Dict[str, Any]] = json.loads(obj["Body"].read())
        logger.info("Loaded %d games", len(games))

        # Generate puzzles
        puzzles = _generate_puzzles(games)
        logger.info("Generated %d puzzles", len(puzzles))

        # POST puzzles back to EC2
        _ingest_puzzles(job_id, puzzles, total_games)

        return {"statusCode": 200, "body": json.dumps({"ok": True, "puzzles": len(puzzles)})}

    except Exception as e:
        logger.error("Error generating puzzles for job %s: %s", job_id, e)
        _update_status(job_id, "failed", error_message=f"Puzzle generation error: {str(e)}")
        raise


# Puzzle generation
def _generate_puzzles(games: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run Stockfish over game list and return puzzle dicts."""
    all_puzzles: List[Dict[str, Any]] = []

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH, timeout=60)
    engine.configure({"Threads": 1, "Hash": 64})

    try:
        for i, game in enumerate(games):
            if len(all_puzzles) >= MAX_TOTAL_PUZZLES:
                break

            pgn = game.get("pgn")
            if not pgn:
                continue

            game_url = game.get("url")
            puzzles = _puzzles_from_pgn(engine, pgn, game_url)

            remaining = MAX_TOTAL_PUZZLES - len(all_puzzles)
            all_puzzles.extend(puzzles[:remaining])

            if (i + 1) % 10 == 0:
                logger.info("Analysed %d/%d games, %d puzzles so far", i + 1, len(games), len(all_puzzles))
    finally:
        engine.quit()

    return all_puzzles


def _puzzles_from_pgn(
    engine: chess.engine.SimpleEngine,
    pgn_string: str,
    game_url: Optional[str],
) -> List[Dict[str, Any]]:
    """Extract up to MAX_PUZZLES_PER_GAME puzzles from a single PGN game."""
    try:
        game = chess.pgn.read_game(StringIO(pgn_string))
        if not game:
            return []

        puzzles: List[Dict[str, Any]] = []
        board = game.board()
        prev_eval: Optional[int] = None
        move_number = 0

        for node in game.mainline():
            move_number += 1
            board.push(node.move)

            if move_number < 10:
                prev_eval = _evaluate(engine, board)
                continue

            curr_eval = _evaluate(engine, board)
            if prev_eval is not None and curr_eval is not None:
                if abs(curr_eval - prev_eval) >= MIN_EVAL_SWING:
                    puzzle_board = board.copy()
                    puzzle_board.pop()
                    puzzle = _make_puzzle(engine, puzzle_board, curr_eval, prev_eval, game_url)
                    if puzzle:
                        puzzles.append(puzzle)
                        if len(puzzles) >= MAX_PUZZLES_PER_GAME:
                            break

            prev_eval = curr_eval

        return puzzles

    except Exception as e:
        logger.error("Error processing game: %s", e)
        return []


def _evaluate(engine: chess.engine.SimpleEngine, board: chess.Board) -> Optional[int]:
    """Return centipawn evaluation from white's perspective, or None on error."""
    try:
        result = engine.analyse(board, chess.engine.Limit(time=TIME_LIMIT, depth=ANALYSIS_DEPTH))
        score = result.get("score")
        if score is None:
            return None
        cp = score.white()
        if cp.is_mate():
            return 10000 if cp.mate() > 0 else -10000
        return cp.score()
    except Exception:
        return None


def _make_puzzle(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    eval_after: int,
    eval_before: int,
    game_url: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Build a puzzle dict from a tactical position."""
    try:
        result = engine.analyse(board, chess.engine.Limit(time=SOLUTION_TIME, depth=SOLUTION_DEPTH))
        pv = result.get("pv", [])
        if len(pv) < 2:
            return None

        solution = [m.uci() for m in pv[:4]]
        theme = _detect_theme(board, pv[0])
        rating = _estimate_rating(abs(eval_after - eval_before), len(pv))

        return {
            "fen": board.fen(),
            "solution": solution,
            "theme": theme,
            "rating": rating,
            "game_url": game_url,
        }
    except Exception:
        return None


def _detect_theme(board: chess.Board, move: chess.Move) -> str:
    piece = board.piece_at(move.from_square)
    if piece is None:
        return "tactic"

    is_capture = board.is_capture(move)
    test_board = board.copy()
    test_board.push(move)
    gives_check = test_board.is_check()

    if move.promotion is not None:
        return "promotion"
    if gives_check and is_capture:
        return "discovered_attack"
    if gives_check:
        return "fork" if _is_fork(test_board, move.to_square) else "check"
    if is_capture:
        captured = board.piece_at(move.to_square)
        if captured and _piece_value(captured) > _piece_value(piece):
            return "winning_material"
        return "capture"
    if _is_fork(test_board, move.to_square):
        return "fork"
    return "tactic"


def _is_fork(board: chess.Board, square: chess.Square) -> bool:
    piece = board.piece_at(square)
    if piece is None:
        return False
    attacks = board.attacks(square)
    valuable = sum(
        1 for sq in attacks
        if (t := board.piece_at(sq)) and t.color != piece.color
        and t.piece_type in (chess.QUEEN, chess.ROOK, chess.KING)
    )
    return valuable >= 2


def _piece_value(piece: chess.Piece) -> int:
    return {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
            chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}.get(piece.piece_type, 0)


def _estimate_rating(eval_swing: int, solution_length: int) -> int:
    rating = 1200
    if eval_swing > 500:
        rating -= 100
    elif eval_swing < 250:
        rating += 150
    rating += (solution_length - 2) * 100
    return max(800, min(2500, rating))


# EC2 API callbacks
def _ingest_puzzles(job_id: str, puzzles: List[Dict[str, Any]], total_games: int) -> None:
    """POST generated puzzles to the EC2 ingest endpoint."""
    payload = {"puzzles": puzzles, "total_games": total_games}
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{EC2_API_URL}/jobs/{job_id}/puzzles/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {LAMBDA_SECRET}"},
        )
        resp.raise_for_status()
    logger.info("Ingested %d puzzles for job %s", len(puzzles), job_id)


def _update_status(
    job_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """POST a status update to the EC2 backend (used for error reporting)."""
    payload: Dict[str, Any] = {"status": status}
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
        logger.warning("Failed to update status to '%s': %s", status, e)
