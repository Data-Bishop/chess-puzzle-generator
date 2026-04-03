"""Worker script for processing jobs from Redis queue."""
import os
import sys
import time
import signal
import random
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from logging_config import configure_logging
from job_queue import queue
from chesscom_client import ChessComClient
from puzzle_generator import PuzzleGenerator, Puzzle as PuzzleData
from database import SessionLocal
from models import Job, Puzzle

logger = logging.getLogger(__name__)


class GameExtractionWorker:
    """Worker that fetches games from Chess.com and generates puzzles."""

    # Configuration
    MAX_PUZZLES_PER_GAME = 2
    MAX_TOTAL_PUZZLES = 20
    MAX_GAMES_TO_ANALYZE = 100  # Cap games before Stockfish analysis to prevent timeouts
    CLEANUP_INTERVAL_SECONDS = 3600  # Run cleanup every hour

    def __init__(self):
        """Initialize worker."""
        self.running = True
        self.chess_client = ChessComClient()
        self.puzzle_generator = PuzzleGenerator()
        self.cleanup_thread = None

        # Handle graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Start cleanup scheduler
        self._start_cleanup_scheduler()

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("Received shutdown signal. Finishing current job...")
        self.running = False

    def _start_cleanup_scheduler(self):
        """Start background thread for periodic cleanup of expired puzzles."""
        def cleanup_loop():
            # Run first cleanup after 60 seconds (give time for startup)
            initial_delay = 60
            for _ in range(initial_delay):
                if not self.running:
                    return
                time.sleep(1)

            while self.running:
                try:
                    self._cleanup_expired_data()
                except Exception as e:
                    logger.error("Error in cleanup: %s", e)

                # Sleep in small increments to allow quick shutdown
                for _ in range(self.CLEANUP_INTERVAL_SECONDS):
                    if not self.running:
                        break
                    time.sleep(1)

        self.cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self.cleanup_thread.start()
        logger.info("Started puzzle cleanup scheduler (runs every hour)")

    def _cleanup_expired_data(self):
        """Delete expired puzzles and old empty jobs."""
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)

            # Delete expired puzzles
            expired_puzzles = db.query(Puzzle).filter(
                Puzzle.expires_at < now
            ).delete(synchronize_session=False)

            # Delete old jobs with no puzzles (older than 24 hours)
            old_empty_jobs = db.query(Job).filter(
                Job.created_at < now - timedelta(hours=24),
                Job.total_puzzles == 0,
                Job.status.in_(["completed", "failed"])
            ).delete(synchronize_session=False)

            db.commit()

            if expired_puzzles > 0 or old_empty_jobs > 0:
                logger.info("Cleanup: deleted %d expired puzzles, %d old empty jobs", expired_puzzles, old_empty_jobs)

        except Exception as e:
            logger.error("Error during cleanup: %s", e)
            db.rollback()
        finally:
            db.close()

    def run(self):
        """Main worker loop."""
        logger.info("Game Extraction Worker started")
        logger.info("Waiting for jobs from Redis queue...")

        while self.running:
            try:
                # Pop job from queue (blocking with 5 second timeout)
                result = queue.pop(timeout=5)

                if not result:
                    # Timeout, no job available - continue waiting
                    continue

                job_id, job_data = result
                logger.info("Processing job %s (username: %s)", job_id, job_data.get("username"))

                # Process the job
                self.process_job(job_id, job_data)

            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error("Error in worker loop: %s", e)
                time.sleep(1)  # Avoid tight loop on persistent errors

        # Cleanup
        self.cleanup()

    def process_job(self, job_id: str, job_data: Dict[str, Any]):
        """
        Process a single job.

        Args:
            job_id: Job UUID
            job_data: Job metadata from queue
        """
        username = job_data.get("username")

        if not username:
            self._update_job_status(job_id, "failed", error="No username provided")
            return

        try:
            # Update job status to processing
            self._update_job_status(job_id, "processing")

            # Extract filters from job data
            date_from = self._parse_datetime(job_data.get("date_from"))
            date_to = self._parse_datetime(job_data.get("date_to"))
            time_control = job_data.get("time_control")

            # Fetch games from Chess.com
            logger.info("Fetching games for user: %s", username)

            if date_from or date_to:
                games = self.chess_client.get_games_by_date_range(
                    username, date_from, date_to
                )
            else:
                # Default: fetch last 3 months
                games = self.chess_client.get_recent_games(
                    username,
                    max_archives=3,
                    time_control=time_control
                )

            logger.info("Fetched %d games", len(games))

            if not games:
                self._update_job_status(
                    job_id,
                    "completed",
                    total_games=0,
                    error="No games found for user"
                )
                return

            # Update status to show we're generating puzzles
            self._update_job_status(
                job_id,
                "generating_puzzles",
                total_games=len(games)
            )

            # Sample games to keep analysis time reasonable
            games_to_analyze = games
            if len(games) > self.MAX_GAMES_TO_ANALYZE:
                games_to_analyze = random.sample(games, self.MAX_GAMES_TO_ANALYZE)
                logger.info("Sampled %d games from %d for analysis", self.MAX_GAMES_TO_ANALYZE, len(games))

            # Generate puzzles from games
            logger.info("Generating puzzles from %d games...", len(games_to_analyze))
            puzzles = self.puzzle_generator.generate_puzzles_from_games(
                games_to_analyze,
                max_puzzles_per_game=self.MAX_PUZZLES_PER_GAME,
                max_total_puzzles=self.MAX_TOTAL_PUZZLES
            )

            logger.info("Generated %d puzzles", len(puzzles))

            # Store puzzles in database
            if puzzles:
                self._store_puzzles(job_id, puzzles)

            # Mark job as completed
            self._update_job_status(
                job_id,
                "completed",
                total_games=len(games),
                total_puzzles=len(puzzles)
            )

            logger.info("Job %s completed — games: %d, puzzles: %d", job_id, len(games), len(puzzles))

        except ValueError as e:
            logger.warning("Validation error for job %s: %s", job_id, e)
            self._update_job_status(job_id, "failed", error=str(e))

        except Exception as e:
            logger.error("Error processing job %s: %s", job_id, e)
            self._update_job_status(
                job_id, "failed", error=f"Unexpected error: {str(e)}"
            )

    def _update_job_status(
        self,
        job_id: str,
        status: str,
        total_games: int = 0,
        total_puzzles: int = 0,
        error: Optional[str] = None
    ):
        """
        Update job status in database.

        Args:
            job_id: Job UUID
            status: New status
            total_games: Number of games fetched
            total_puzzles: Number of puzzles generated
            error: Error message if failed
        """
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()

            if not job:
                logger.warning("Job %s not found in database", job_id)
                return

            job.status = status
            job.total_games = total_games
            job.total_puzzles = total_puzzles

            if error:
                job.error_message = error

            if status in ["completed", "failed"]:
                job.completed_at = datetime.now(timezone.utc)

            db.commit()
            logger.info("Job %s status → %s", job_id, status)

        except Exception as e:
            logger.error("Error updating job status: %s", e)
            db.rollback()
        finally:
            db.close()

    def _store_puzzles(self, job_id: str, puzzles: List[PuzzleData]):
        """
        Store generated puzzles in database.

        Args:
            job_id: Job UUID
            puzzles: List of Puzzle dataclass objects from puzzle_generator
        """
        db = SessionLocal()
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

            for puzzle_data in puzzles:
                puzzle = Puzzle(
                    job_id=job_id,
                    fen=puzzle_data.fen,
                    solution=puzzle_data.solution,
                    theme=puzzle_data.theme,
                    rating=puzzle_data.rating,
                    game_url=puzzle_data.game_url,
                    expires_at=expires_at
                )
                db.add(puzzle)

            db.commit()
            logger.info("Stored %d puzzles in database", len(puzzles))

        except Exception as e:
            logger.error("Error storing puzzles: %s", e)
            db.rollback()
        finally:
            db.close()

    def _parse_datetime(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

    def cleanup(self):
        """Cleanup resources."""
        logger.info("Cleaning up worker resources...")
        self.chess_client.close()
        self.puzzle_generator.close()
        logger.info("Worker stopped")


def main():
    """Entry point for worker."""
    configure_logging()
    logger.info("Starting Chess Puzzle Generator Worker")
    logger.info("Python version: %s", sys.version.split()[0])
    logger.info("Working directory: %s", os.getcwd())

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    logger.info("Redis URL: %s", redis_url)

    # Start worker
    worker = GameExtractionWorker()

    try:
        worker.run()
    except Exception as e:
        logger.critical("Fatal error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
