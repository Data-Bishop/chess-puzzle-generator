"""Chess.com API client for fetching player games."""
import httpx
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class ChessComClient:
    """Client for Chess.com Public API."""

    BASE_URL = "https://api.chess.com/pub"

    def __init__(self):
        """Initialize HTTP client."""
        self.client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Chess Puzzle Generator (Educational Project)"
            }
        )

    def get_player_archives(self, username: str) -> List[str]:
        """
        Get list of monthly archive URLs for a player.

        Args:
            username: Chess.com username

        Returns:
            List of archive URLs (e.g., ["https://api.chess.com/pub/player/hikaru/games/2024/01", ...])

        Raises:
            httpx.HTTPError: If API request fails
        """
        url = f"{self.BASE_URL}/player/{username}/games/archives"

        try:
            response = self.client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("archives", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError(f"Player '{username}' not found")
            raise
        except Exception as e:
            raise Exception(f"Error fetching archives for {username}: {e}")

    def get_monthly_games(self, archive_url: str) -> List[Dict[str, Any]]:
        """
        Get all games from a monthly archive.

        Args:
            archive_url: Full URL to monthly archive

        Returns:
            List of game objects with metadata and PGN

        Raises:
            httpx.HTTPError: If API request fails
        """
        try:
            response = self.client.get(archive_url)
            response.raise_for_status()
            data = response.json()
            return data.get("games", [])
        except Exception as e:
            raise Exception(f"Error fetching games from {archive_url}: {e}")

    def get_recent_games(
        self,
        username: str,
        max_archives: int = 3,
        time_control: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent games for a player.

        Args:
            username: Chess.com username
            max_archives: Number of recent monthly archives to fetch
            time_control: Optional filter (e.g., "blitz", "rapid", "bullet")

        Returns:
            List of game objects

        Raises:
            Exception: If fetching fails
        """
        # Get list of archives
        archives = self.get_player_archives(username)

        if not archives:
            return []

        # Get most recent archives
        recent_archives = archives[-max_archives:]

        all_games = []

        for archive_url in recent_archives:
            try:
                games = self.get_monthly_games(archive_url)

                # Filter by time control if specified
                if time_control:
                    games = [
                        game for game in games
                        if self._matches_time_control(game, time_control)
                    ]

                all_games.extend(games)

                # Be nice to Chess.com API (avoid rate limiting)
                time.sleep(0.1)

            except Exception as e:
                logger.warning("Failed to fetch %s: %s", archive_url, e)
                continue

        return all_games

    def get_games_by_date_range(
        self,
        username: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Get games within a date range.

        Args:
            username: Chess.com username
            date_from: Start date (inclusive)
            date_to: End date (inclusive)

        Returns:
            List of game objects within date range
        """
        archives = self.get_player_archives(username)

        if not archives:
            return []

        # Filter archives by date range
        filtered_archives = self._filter_archives_by_date(
            archives, date_from, date_to
        )

        all_games = []

        for archive_url in filtered_archives:
            try:
                games = self.get_monthly_games(archive_url)

                # Further filter games by exact timestamp if needed
                if date_from or date_to:
                    games = self._filter_games_by_timestamp(
                        games, date_from, date_to
                    )

                all_games.extend(games)
                time.sleep(0.1)

            except Exception as e:
                logger.warning("Failed to fetch %s: %s", archive_url, e)
                continue

        return all_games

    def _matches_time_control(self, game: Dict[str, Any], time_control: str) -> bool:
        """Check if game matches time control filter."""
        tc = game.get("time_class", "").lower()
        return tc == time_control.lower()

    def _filter_archives_by_date(
        self,
        archives: List[str],
        date_from: Optional[datetime],
        date_to: Optional[datetime]
    ) -> List[str]:
        """Filter archive URLs by date range."""
        if not date_from and not date_to:
            return archives

        filtered = []

        for archive_url in archives:
            # Extract year/month from URL (e.g., .../2024/01)
            parts = archive_url.rstrip("/").split("/")
            try:
                year = int(parts[-2])
                month = int(parts[-1])
                archive_date = datetime(year, month, 1)

                if date_from and archive_date < datetime(date_from.year, date_from.month, 1):
                    continue
                if date_to and archive_date > datetime(date_to.year, date_to.month, 1):
                    continue

                filtered.append(archive_url)
            except (ValueError, IndexError):
                # Invalid URL format, skip
                continue

        return filtered

    def _filter_games_by_timestamp(
        self,
        games: List[Dict[str, Any]],
        date_from: Optional[datetime],
        date_to: Optional[datetime]
    ) -> List[Dict[str, Any]]:
        """Filter games by exact timestamp."""
        filtered = []

        for game in games:
            # Chess.com uses "end_time" as Unix timestamp
            end_time = game.get("end_time")
            if not end_time:
                continue

            game_date = datetime.fromtimestamp(end_time)

            if date_from and game_date < date_from:
                continue
            if date_to and game_date > date_to:
                continue

            filtered.append(game)

        return filtered

    def close(self):
        """Close HTTP client."""
        self.client.close()
