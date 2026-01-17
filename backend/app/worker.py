"""Worker script for processing jobs from Redis queue."""
import os
import sys
import time
import signal
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from job_queue import queue
from chesscom_client import ChessComClient
from puzzle_generator import PuzzleGenerator, Puzzle as PuzzleData
from database import SessionLocal
from models import Job, Puzzle


class GameExtractionWorker:
    """Worker that fetches games from Chess.com and generates puzzles."""

    # Configuration
    MAX_PUZZLES_PER_GAME = 2
    MAX_TOTAL_PUZZLES = 20

    def __init__(self):
        """Initialize worker."""
        self.running = True
        self.chess_client = ChessComClient()
        self.puzzle_generator = PuzzleGenerator()

        # Handle graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\nReceived shutdown signal. Finishing current job...")
        self.running = False

    def run(self):
        """Main worker loop."""
        print("Game Extraction Worker started")
        print("Waiting for jobs from Redis queue...")

        while self.running:
            try:
                # Pop job from queue (blocking with 5 second timeout)
                result = queue.pop(timeout=5)

                if not result:
                    # Timeout, no job available - continue waiting
                    continue

                job_id, job_data = result
                print(f"\n{'='*60}")
                print(f"Processing job: {job_id}")
                print(f"Username: {job_data.get('username')}")
                print(f"{'='*60}")

                # Process the job
                self.process_job(job_id, job_data)

            except KeyboardInterrupt:
                print("\nShutting down...")
                break
            except Exception as e:
                print(f"Error in worker loop: {e}")
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
            print(f"Fetching games for user: {username}")

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

            print(f"Fetched {len(games)} games")

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

            # Generate puzzles from games
            print(f"Generating puzzles from {len(games)} games...")
            puzzles = self.puzzle_generator.generate_puzzles_from_games(
                games,
                max_puzzles_per_game=self.MAX_PUZZLES_PER_GAME,
                max_total_puzzles=self.MAX_TOTAL_PUZZLES
            )

            print(f"Generated {len(puzzles)} puzzles")

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

            print(f"Job {job_id} completed successfully")
            print(f"Total games: {len(games)}, Total puzzles: {len(puzzles)}")

        except ValueError as e:
            # User not found or invalid input
            print(f"Validation error: {e}")
            self._update_job_status(job_id, "failed", error=str(e))

        except Exception as e:
            # Unexpected error
            print(f"Error processing job {job_id}: {e}")
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
                print(f"Warning: Job {job_id} not found in database")
                return

            job.status = status
            job.total_games = total_games
            job.total_puzzles = total_puzzles

            if error:
                job.error_message = error

            if status in ["completed", "failed"]:
                job.completed_at = datetime.utcnow()

            db.commit()
            print(f"Updated job status to: {status}")

        except Exception as e:
            print(f"Error updating job status: {e}")
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
            expires_at = datetime.utcnow() + timedelta(hours=24)

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
            print(f"Stored {len(puzzles)} puzzles in database")

        except Exception as e:
            print(f"Error storing puzzles: {e}")
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
        print("Cleaning up worker resources...")
        self.chess_client.close()
        self.puzzle_generator.close()
        print("Worker stopped")


def main():
    """Entry point for worker."""
    print("Starting Chess Puzzle Generator Worker")
    print(f"Python version: {sys.version}")
    print(f"Working directory: {os.getcwd()}")

    # Check environment
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    print(f"Redis URL: {redis_url}")

    # Start worker
    worker = GameExtractionWorker()

    try:
        worker.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
