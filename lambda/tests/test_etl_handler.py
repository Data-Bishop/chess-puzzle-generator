"""Tests for the ETL Lambda handler."""
import json
import time
import pytest
import respx
import httpx
import boto3
from moto import mock_aws
from unittest.mock import patch

import etl.handler as handler


# Fixtures
ARCHIVES_RESPONSE = {
    "archives": [
        "https://api.chess.com/pub/player/hikaru/games/2024/01",
        "https://api.chess.com/pub/player/hikaru/games/2024/02",
        "https://api.chess.com/pub/player/hikaru/games/2024/03",
    ]
}

SAMPLE_GAME = {
    "pgn": "[Event '?']\n1. e4 e5 *",
    "time_class": "blitz",
    "url": "https://www.chess.com/game/live/123",
    "end_time": 1706745600,
}

MONTHLY_GAMES = {"games": [SAMPLE_GAME, SAMPLE_GAME]}

BASE_EVENT = {
    "job_id": "aaaaaaaa-0000-0000-0000-000000000001",
    "username": "hikaru",
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)


@pytest.fixture()
def s3_bucket():
    """Moto-backed S3 bucket matching the test env var."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="eu-north-1")
        s3.create_bucket(
            Bucket="test-chess-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-north-1"},
        )
        yield s3


def _chess_com_router(archives=None, games=None, player_status=200):
    """Shared respx router simulating Chess.com responses."""
    router = respx.MockRouter(assert_all_called=False)
    if player_status == 404:
        router.get(
            "https://api.chess.com/pub/player/hikaru/games/archives"
        ).mock(return_value=httpx.Response(404))
    else:
        router.get(
            "https://api.chess.com/pub/player/hikaru/games/archives"
        ).mock(return_value=httpx.Response(200, json=archives or ARCHIVES_RESPONSE))
        for url in (archives or ARCHIVES_RESPONSE)["archives"]:
            router.get(url).mock(return_value=httpx.Response(200, json=games or MONTHLY_GAMES))
    return router


def _ec2_router():
    """respx router that accepts any POST to the EC2 status endpoint."""
    router = respx.MockRouter(assert_all_called=False)
    router.post(
        url__regex=r"http://ec2-test:8000/jobs/.+/status"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))
    return router


# handler() — happy path
class TestHandlerHappyPath:
    def test_returns_200(self, s3_bucket):
        with _chess_com_router(), _ec2_router(), \
                patch.object(handler, "lambda_client") as mock_lc:
            mock_lc.invoke.return_value = {"StatusCode": 202}
            result = handler.handler(BASE_EVENT, {})
        assert result["statusCode"] == 200

    def test_stores_games_in_s3(self, s3_bucket):
        with _chess_com_router(), _ec2_router(), \
                patch.object(handler, "lambda_client") as mock_lc:
            mock_lc.invoke.return_value = {"StatusCode": 202}
            handler.handler(BASE_EVENT, {})

        obj = s3_bucket.get_object(
            Bucket="test-chess-bucket",
            Key=f"{BASE_EVENT['job_id']}/games.json",
        )
        games = json.loads(obj["Body"].read())
        assert isinstance(games, list)
        assert len(games) > 0

    def test_invokes_puzzles_lambda_async(self, s3_bucket):
        with _chess_com_router(), _ec2_router(), \
                patch.object(handler, "lambda_client") as mock_lc:
            mock_lc.invoke.return_value = {"StatusCode": 202}
            handler.handler(BASE_EVENT, {})

        mock_lc.invoke.assert_called_once()
        kwargs = mock_lc.invoke.call_args[1]
        assert kwargs["InvocationType"] == "Event"
        payload = json.loads(kwargs["Payload"])
        assert payload["job_id"] == BASE_EVENT["job_id"]
        assert "s3_key" in payload

    def test_sends_processing_then_generating_puzzles_status(self, s3_bucket):
        statuses = []

        def capture(request):
            statuses.append(json.loads(request.content)["status"])
            return httpx.Response(200, json={"ok": True})

        router = respx.MockRouter(assert_all_called=False)
        router.post(url__regex=r"http://ec2-test:8000/jobs/.+/status").mock(
            side_effect=capture
        )

        with _chess_com_router(), router, \
                patch.object(handler, "lambda_client") as mock_lc:
            mock_lc.invoke.return_value = {"StatusCode": 202}
            handler.handler(BASE_EVENT, {})

        assert statuses[0] == "processing"
        assert "generating_puzzles" in statuses


# handler() — no games found
class TestHandlerNoGames:
    def test_returns_200_when_no_games(self, s3_bucket):
        with _chess_com_router(games={"games": []}), _ec2_router(), \
                patch.object(handler, "lambda_client"):
            result = handler.handler(BASE_EVENT, {})
        assert result["statusCode"] == 200

    def test_sets_failed_status_when_no_games(self, s3_bucket):
        statuses = []

        def capture(request):
            statuses.append(json.loads(request.content)["status"])
            return httpx.Response(200)

        router = respx.MockRouter(assert_all_called=False)
        router.post(url__regex=r"http://ec2-test:8000/jobs/.+/status").mock(
            side_effect=capture
        )

        with _chess_com_router(games={"games": []}), router, \
                patch.object(handler, "lambda_client"):
            handler.handler(BASE_EVENT, {})

        assert "failed" in statuses

    def test_does_not_invoke_puzzles_lambda_when_no_games(self, s3_bucket):
        with _chess_com_router(games={"games": []}), _ec2_router(), \
                patch.object(handler, "lambda_client") as mock_lc:
            handler.handler(BASE_EVENT, {})
        mock_lc.invoke.assert_not_called()


# handler() — player not found
class TestHandlerPlayerNotFound:
    def test_sets_failed_status_on_404(self, s3_bucket):
        statuses = []

        def capture(request):
            statuses.append(json.loads(request.content)["status"])
            return httpx.Response(200)

        router = respx.MockRouter(assert_all_called=False)
        router.post(url__regex=r"http://ec2-test:8000/jobs/.+/status").mock(
            side_effect=capture
        )

        with _chess_com_router(player_status=404), router, \
                patch.object(handler, "lambda_client"):
            handler.handler(BASE_EVENT, {})

        assert "failed" in statuses

    def test_does_not_raise_on_player_not_found(self, s3_bucket):
        with _chess_com_router(player_status=404), _ec2_router(), \
                patch.object(handler, "lambda_client"):
            result = handler.handler(BASE_EVENT, {})
        assert result["statusCode"] == 200


# handler() — game sampling
class TestHandlerSampling:
    def test_samples_down_to_max_when_over_limit(self, s3_bucket):
        many_games = {"games": [SAMPLE_GAME] * 150}
        with _chess_com_router(games=many_games), _ec2_router(), \
                patch.object(handler, "lambda_client") as mock_lc:
            mock_lc.invoke.return_value = {"StatusCode": 202}
            handler.handler(BASE_EVENT, {})

        obj = s3_bucket.get_object(
            Bucket="test-chess-bucket",
            Key=f"{BASE_EVENT['job_id']}/games.json",
        )
        stored = json.loads(obj["Body"].read())
        assert len(stored) == handler.MAX_GAMES_TO_SAMPLE

    def test_all_games_kept_when_under_limit(self, s3_bucket):
        few_games = {"games": [SAMPLE_GAME] * 5}
        with _chess_com_router(games=few_games), _ec2_router(), \
                patch.object(handler, "lambda_client") as mock_lc:
            mock_lc.invoke.return_value = {"StatusCode": 202}
            handler.handler(BASE_EVENT, {})

        obj = s3_bucket.get_object(
            Bucket="test-chess-bucket",
            Key=f"{BASE_EVENT['job_id']}/games.json",
        )
        stored = json.loads(obj["Body"].read())
        # 3 archives × 5 games each = 15 total — under the 100 cap
        assert len(stored) == 15


# _fetch_games helpers
class TestFetchGames:
    @respx.mock
    def test_time_control_filter_applied(self):
        mixed = {"games": [
            {**SAMPLE_GAME, "time_class": "blitz"},
            {**SAMPLE_GAME, "time_class": "rapid"},
        ]}
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(200, json=ARCHIVES_RESPONSE)
        )
        for url in ARCHIVES_RESPONSE["archives"]:
            respx.get(url).mock(return_value=httpx.Response(200, json=mixed))

        games = handler._fetch_games("hikaru", time_control="blitz", date_from=None, date_to=None)
        assert all(g["time_class"] == "blitz" for g in games)

    @respx.mock
    def test_defaults_to_last_three_archives_when_no_date_filter(self):
        all_archives = {
            "archives": [
                f"https://api.chess.com/pub/player/hikaru/games/2023/{m:02d}"
                for m in range(1, 13)
            ] + list(ARCHIVES_RESPONSE["archives"])
        }
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(200, json=all_archives)
        )
        for url in ARCHIVES_RESPONSE["archives"]:
            respx.get(url).mock(return_value=httpx.Response(200, json=MONTHLY_GAMES))

        games = handler._fetch_games("hikaru", time_control=None, date_from=None, date_to=None)
        assert len(games) == 6  # 3 archives × 2 games

    @respx.mock
    def test_player_not_found_raises_value_error(self):
        respx.get("https://api.chess.com/pub/player/ghost/games/archives").mock(
            return_value=httpx.Response(404)
        )
        with pytest.raises(ValueError, match="not found"):
            handler._fetch_games("ghost", None, None, None)

    @respx.mock
    def test_failed_archive_fetch_is_skipped(self):
        respx.get("https://api.chess.com/pub/player/hikaru/games/archives").mock(
            return_value=httpx.Response(200, json=ARCHIVES_RESPONSE)
        )
        # First two archives fail, last one succeeds
        respx.get(ARCHIVES_RESPONSE["archives"][0]).mock(
            side_effect=httpx.ConnectError("timeout")
        )
        respx.get(ARCHIVES_RESPONSE["archives"][1]).mock(
            side_effect=httpx.ConnectError("timeout")
        )
        respx.get(ARCHIVES_RESPONSE["archives"][2]).mock(
            return_value=httpx.Response(200, json=MONTHLY_GAMES)
        )

        games = handler._fetch_games("hikaru", None, None, None)
        assert len(games) == 2  # only the one successful archive


# _filter_archives_by_date
class TestFilterArchivesByDate:
    def test_no_filter_returns_all(self):
        result = handler._filter_archives_by_date(ARCHIVES_RESPONSE["archives"], None, None)
        assert result == ARCHIVES_RESPONSE["archives"]

    def test_date_from_excludes_earlier(self):
        from datetime import datetime
        result = handler._filter_archives_by_date(
            ARCHIVES_RESPONSE["archives"],
            date_from=datetime(2024, 2, 1),
            date_to=None,
        )
        assert all("2024/01" not in u for u in result)
        assert len(result) == 2

    def test_date_to_excludes_later(self):
        from datetime import datetime
        result = handler._filter_archives_by_date(
            ARCHIVES_RESPONSE["archives"],
            date_from=None,
            date_to=datetime(2024, 2, 28),
        )
        assert all("2024/03" not in u for u in result)
        assert len(result) == 2

    def test_malformed_url_skipped(self):
        result = handler._filter_archives_by_date(["https://bad/url"], None, None)
        assert result == []


# _update_status — auth and error suppression
class TestUpdateStatus:
    @respx.mock
    def test_sends_correct_bearer_token(self):
        received = {}

        def capture(request):
            received["auth"] = request.headers.get("authorization")
            return httpx.Response(200)

        respx.post("http://ec2-test:8000/jobs/job-1/status").mock(side_effect=capture)
        handler._update_status("job-1", "processing")
        assert received["auth"] == "Bearer test-secret"

    @respx.mock
    def test_does_not_raise_on_network_error(self):
        respx.post("http://ec2-test:8000/jobs/job-1/status").mock(
            side_effect=httpx.ConnectError("down")
        )
        # Must not raise — callback failures are suppressed
        handler._update_status("job-1", "failed", error_message="boom")
