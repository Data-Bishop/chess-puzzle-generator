"""Tests for the Chess.com API client."""
import time
import pytest
import respx
import httpx
from datetime import datetime, timezone
from unittest.mock import patch

from chesscom_client import ChessComClient


ARCHIVES_RESPONSE = {
    "archives": [
        "https://api.chess.com/pub/player/hikaru/games/2024/01",
        "https://api.chess.com/pub/player/hikaru/games/2024/02",
        "https://api.chess.com/pub/player/hikaru/games/2024/03",
    ]
}

GAME_BLITZ = {
    "time_class": "blitz",
    "end_time": int(datetime(2024, 2, 15).timestamp()),
    "white": {"username": "hikaru", "result": "win"},
    "black": {"username": "opponent", "result": "lose"},
    "pgn": "[Event '?']\n1. e4 e5 *",
}

GAME_RAPID = {
    "time_class": "rapid",
    "end_time": int(datetime(2024, 2, 20).timestamp()),
    "white": {"username": "opponent", "result": "lose"},
    "black": {"username": "hikaru", "result": "win"},
    "pgn": "[Event '?']\n1. d4 d5 *",
}

MONTHLY_GAMES = {"games": [GAME_BLITZ, GAME_RAPID]}


@pytest.fixture()
def client():
    c = ChessComClient()
    yield c
    c.close()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Remove the 0.1 s courtesy sleep so tests don't slow down."""
    monkeypatch.setattr(time, "sleep", lambda _: None)


# get_player_archives
class TestGetPlayerArchives:
    @respx.mock
    def test_returns_archive_list(self, client):
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(200, json=ARCHIVES_RESPONSE)
        )
        archives = client.get_player_archives("hikaru")
        assert len(archives) == 3
        assert archives[0].endswith("2024/01")

    @respx.mock
    def test_empty_archives_returned_when_key_missing(self, client):
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(200, json={})
        )
        assert client.get_player_archives("hikaru") == []

    @respx.mock
    def test_404_raises_value_error(self, client):
        respx.get("https://api.chess.com/pub/player/ghost/games/archives").mock(
            return_value=httpx.Response(404)
        )
        with pytest.raises(ValueError, match="not found"):
            client.get_player_archives("ghost")

    @respx.mock
    def test_server_error_re_raises(self, client):
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(500)
        )
        with pytest.raises(Exception):
            client.get_player_archives("hikaru")


# get_monthly_games
class TestGetMonthlyGames:
    @respx.mock
    def test_returns_games_list(self, client):
        url = "https://api.chess.com/pub/player/hikaru/games/2024/02"
        respx.get(url).mock(return_value=httpx.Response(200, json=MONTHLY_GAMES))
        games = client.get_monthly_games(url)
        assert len(games) == 2

    @respx.mock
    def test_empty_games_key_returns_empty_list(self, client):
        url = "https://api.chess.com/pub/player/hikaru/games/2024/02"
        respx.get(url).mock(return_value=httpx.Response(200, json={}))
        assert client.get_monthly_games(url) == []


# get_recent_games
class TestGetRecentGames:
    @respx.mock
    def test_fetches_most_recent_archives(self, client):
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(200, json=ARCHIVES_RESPONSE)
        )
        # Only the last archive (2024/03) should be requested with max_archives=1
        respx.get("https://api.chess.com/pub/player/hikaru/games/2024/03").mock(
            return_value=httpx.Response(200, json=MONTHLY_GAMES)
        )
        games = client.get_recent_games("hikaru", max_archives=1)
        assert len(games) == 2

    @respx.mock
    def test_time_control_filter_applied(self, client):
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(200, json=ARCHIVES_RESPONSE)
        )
        respx.get("https://api.chess.com/pub/player/hikaru/games/2024/03").mock(
            return_value=httpx.Response(200, json=MONTHLY_GAMES)
        )
        games = client.get_recent_games("hikaru", max_archives=1, time_control="blitz")
        assert all(g["time_class"] == "blitz" for g in games)
        assert len(games) == 1

    @respx.mock
    def test_no_archives_returns_empty(self, client):
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(200, json={"archives": []})
        )
        assert client.get_recent_games("hikaru") == []

    @respx.mock
    def test_failed_archive_fetch_is_skipped(self, client):
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(200, json=ARCHIVES_RESPONSE)
        )
        respx.get("https://api.chess.com/pub/player/hikaru/games/2024/03").mock(
            side_effect=httpx.ConnectError("timeout")
        )
        # Should not raise — archive errors are swallowed
        games = client.get_recent_games("hikaru", max_archives=1)
        assert games == []


# _filter_archives_by_date
class TestFilterArchivesByDate:
    def test_no_filter_returns_all(self, client):
        result = client._filter_archives_by_date(ARCHIVES_RESPONSE["archives"], None, None)
        assert result == ARCHIVES_RESPONSE["archives"]

    def test_date_from_excludes_earlier_archives(self, client):
        result = client._filter_archives_by_date(
            ARCHIVES_RESPONSE["archives"],
            date_from=datetime(2024, 2, 1),
            date_to=None,
        )
        assert all("2024/01" not in url for url in result)
        assert len(result) == 2

    def test_date_to_excludes_later_archives(self, client):
        result = client._filter_archives_by_date(
            ARCHIVES_RESPONSE["archives"],
            date_from=None,
            date_to=datetime(2024, 2, 28),
        )
        assert all("2024/03" not in url for url in result)
        assert len(result) == 2

    def test_exact_month_match(self, client):
        result = client._filter_archives_by_date(
            ARCHIVES_RESPONSE["archives"],
            date_from=datetime(2024, 2, 1),
            date_to=datetime(2024, 2, 28),
        )
        assert len(result) == 1
        assert "2024/02" in result[0]

    def test_malformed_url_skipped(self, client):
        bad_archives = ["https://bad-url/no-date"]
        result = client._filter_archives_by_date(bad_archives, datetime(2024, 1, 1), None)
        assert result == []


# _filter_games_by_timestamp
class TestFilterGamesByTimestamp:
    def test_no_filter_skips_games_without_end_time(self, client):
        games = [{"time_class": "blitz"}]  # no end_time
        result = client._filter_games_by_timestamp(games, None, None)
        assert result == []

    def test_date_from_excludes_older_games(self, client):
        result = client._filter_games_by_timestamp(
            [GAME_BLITZ, GAME_RAPID],
            date_from=datetime(2024, 2, 18),
            date_to=None,
        )
        assert len(result) == 1
        assert result[0]["time_class"] == "rapid"

    def test_date_to_excludes_newer_games(self, client):
        result = client._filter_games_by_timestamp(
            [GAME_BLITZ, GAME_RAPID],
            date_from=None,
            date_to=datetime(2024, 2, 16),
        )
        assert len(result) == 1
        assert result[0]["time_class"] == "blitz"

    def test_both_bounds_applied(self, client):
        result = client._filter_games_by_timestamp(
            [GAME_BLITZ, GAME_RAPID],
            date_from=datetime(2024, 2, 14),
            date_to=datetime(2024, 2, 16),
        )
        assert len(result) == 1
        assert result[0]["time_class"] == "blitz"


# _matches_time_control
class TestMatchesTimeControl:
    def test_match_is_case_insensitive(self, client):
        game = {"time_class": "Blitz"}
        assert client._matches_time_control(game, "blitz") is True

    def test_no_match(self, client):
        game = {"time_class": "rapid"}
        assert client._matches_time_control(game, "blitz") is False

    def test_missing_time_class_does_not_match(self, client):
        assert client._matches_time_control({}, "blitz") is False
