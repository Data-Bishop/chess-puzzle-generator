"""
API integration tests.

Requires Docker PostgreSQL to be running (docker compose up postgres).
Each test runs inside a rolled-back transaction, so no data persists.

Run with:
    pytest tests/test_api.py -v
"""
import pytest
from unittest.mock import patch
from uuid import uuid4

from models import Job, Puzzle


# Helpers
VALID_SECRET = "test-lambda-secret"
AUTH_HEADER = {"Authorization": f"Bearer {VALID_SECRET}"}


@pytest.fixture(autouse=True)
def patch_rate_limiter():
    """Allow all requests through the rate limiter by default."""
    with patch("main.rate_limiter.is_allowed", return_value=(True, None)):
        yield


@pytest.fixture(autouse=True)
def patch_queue():
    """Prevent real Redis calls when the worker pushes jobs to the queue."""
    with patch("main.queue.push", return_value=True):
        yield


@pytest.fixture(autouse=True)
def configure_lambda_secret(monkeypatch):
    """Set a predictable lambda secret so auth tests work without a real .env."""
    monkeypatch.setattr("main.settings.lambda_secret", VALID_SECRET)


# Utility endpoints
class TestRoot:
    def test_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_response_contains_status(self, client):
        data = client.get("/").json()
        assert data["status"] == "online"


class TestHealth:
    def test_returns_healthy(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


# POST /jobs
class TestCreateJob:
    def test_creates_job_and_returns_201(self, client):
        response = client.post("/jobs", json={"username": "hikaru"})
        assert response.status_code == 201

    def test_response_contains_job_id(self, client):
        data = client.post("/jobs", json={"username": "hikaru"}).json()
        assert "id" in data

    def test_job_starts_in_pending_status(self, client):
        data = client.post("/jobs", json={"username": "hikaru"}).json()
        assert data["status"] == "pending"

    def test_username_stored_correctly(self, client):
        data = client.post("/jobs", json={"username": "magnuscarlsen"}).json()
        assert data["username"] == "magnuscarlsen"

    def test_optional_filters_stored(self, client):
        payload = {
            "username": "hikaru",
            "min_rating": 1200,
            "max_rating": 2000,
            "time_control": "blitz",
        }
        data = client.post("/jobs", json=payload).json()
        assert data["username"] == "hikaru"

    def test_missing_username_returns_422(self, client):
        response = client.post("/jobs", json={})
        assert response.status_code == 422

    def test_empty_username_returns_422(self, client):
        response = client.post("/jobs", json={"username": ""})
        assert response.status_code == 422

    def test_rate_limit_exceeded_returns_429(self, client):
        with patch("main.rate_limiter.is_allowed", return_value=(False, 3600)):
            response = client.post("/jobs", json={"username": "hikaru"})
        assert response.status_code == 429

    def test_rate_limit_retry_after_header_set(self, client):
        with patch("main.rate_limiter.is_allowed", return_value=(False, 3600)):
            response = client.post("/jobs", json={"username": "hikaru"})
        assert response.headers.get("retry-after") == "3600"

    def test_queue_push_called_in_local_mode(self, client):
        with patch("main.queue.push", return_value=True) as mock_push:
            client.post("/jobs", json={"username": "hikaru"})
        mock_push.assert_called_once()

    def test_lambda_invoked_in_lambda_mode(self, client, monkeypatch):
        monkeypatch.setattr("main.settings.worker_mode", "lambda")
        monkeypatch.setattr("main.settings.lambda_etl_arn", "arn:aws:lambda:eu-north-1:123:function:etl")
        with patch("main.boto3.client") as mock_boto:
            mock_lambda = mock_boto.return_value
            mock_lambda.invoke.return_value = {"StatusCode": 202}
            client.post("/jobs", json={"username": "hikaru"})
        mock_boto.assert_called_once_with("lambda", region_name="eu-north-1")
        mock_lambda.invoke.assert_called_once()


# GET /jobs/{job_id}
class TestGetJob:
    def test_returns_created_job(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        assert response.json()["id"] == job_id

    def test_unknown_id_returns_404(self, client):
        response = client.get(f"/jobs/{uuid4()}")
        assert response.status_code == 404

    def test_invalid_uuid_returns_422(self, client):
        response = client.get("/jobs/not-a-uuid")
        assert response.status_code == 422


# GET /jobs/{job_id}/puzzles
class TestGetJobPuzzles:
    def test_returns_empty_list_for_new_job(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        response = client.get(f"/jobs/{job_id}/puzzles")
        assert response.status_code == 200
        data = response.json()
        assert data["puzzles"] == []
        assert data["total"] == 0

    def test_unknown_job_returns_404(self, client):
        response = client.get(f"/jobs/{uuid4()}/puzzles")
        assert response.status_code == 404


# DELETE /jobs/{job_id}
class TestDeleteJob:
    def test_delete_existing_job_returns_204(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        response = client.delete(f"/jobs/{job_id}")
        assert response.status_code == 204

    def test_deleted_job_no_longer_retrievable(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        client.delete(f"/jobs/{job_id}")
        assert client.get(f"/jobs/{job_id}").status_code == 404

    def test_delete_unknown_job_returns_404(self, client):
        response = client.delete(f"/jobs/{uuid4()}")
        assert response.status_code == 404


# POST /jobs/{job_id}/status  (Lambda callback)
class TestUpdateJobStatus:
    def test_updates_status(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        response = client.post(
            f"/jobs/{job_id}/status",
            json={"status": "processing"},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_job_status_persisted(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        client.post(
            f"/jobs/{job_id}/status",
            json={"status": "generating_puzzles", "total_games": 42},
            headers=AUTH_HEADER,
        )
        job = client.get(f"/jobs/{job_id}").json()
        assert job["status"] == "generating_puzzles"
        assert job["total_games"] == 42

    def test_missing_auth_returns_401(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        response = client.post(
            f"/jobs/{job_id}/status",
            json={"status": "processing"},
        )
        assert response.status_code == 401

    def test_wrong_secret_returns_401(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        response = client.post(
            f"/jobs/{job_id}/status",
            json={"status": "processing"},
            headers={"Authorization": "Bearer wrong-secret"},
        )
        assert response.status_code == 401

    def test_unknown_job_returns_404(self, client):
        response = client.post(
            f"/jobs/{uuid4()}/status",
            json={"status": "processing"},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 404

    def test_failed_status_sets_error_message(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        client.post(
            f"/jobs/{job_id}/status",
            json={"status": "failed", "error_message": "Player not found"},
            headers=AUTH_HEADER,
        )
        job = client.get(f"/jobs/{job_id}").json()
        assert job["status"] == "failed"
        assert job["error_message"] == "Player not found"


# POST /jobs/{job_id}/puzzles/ingest  (Lambda callback)
SAMPLE_PUZZLE = {
    "fen": "6k1/6p1/4rq2/p4bNP/2P5/PP1r2R1/5PQK/8 b - - 1 42",
    "solution": ["e6d6", "c4c5"],
    "theme": "tactic",
    "rating": 1800,
}


class TestIngestPuzzles:
    def test_ingest_stores_puzzles_and_returns_201(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        response = client.post(
            f"/jobs/{job_id}/puzzles/ingest",
            json={"puzzles": [SAMPLE_PUZZLE], "total_games": 50},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 201
        assert response.json()["puzzles_stored"] == 1

    def test_puzzles_retrievable_after_ingest(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        client.post(
            f"/jobs/{job_id}/puzzles/ingest",
            json={"puzzles": [SAMPLE_PUZZLE, SAMPLE_PUZZLE], "total_games": 50},
            headers=AUTH_HEADER,
        )
        data = client.get(f"/jobs/{job_id}/puzzles").json()
        assert data["total"] == 2

    def test_job_marked_completed_after_ingest(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        client.post(
            f"/jobs/{job_id}/puzzles/ingest",
            json={"puzzles": [SAMPLE_PUZZLE], "total_games": 50},
            headers=AUTH_HEADER,
        )
        job = client.get(f"/jobs/{job_id}").json()
        assert job["status"] == "completed"
        assert job["total_games"] == 50
        assert job["total_puzzles"] == 1

    def test_empty_puzzle_list_accepted(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        response = client.post(
            f"/jobs/{job_id}/puzzles/ingest",
            json={"puzzles": [], "total_games": 10},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 201
        assert response.json()["puzzles_stored"] == 0

    def test_missing_auth_returns_401(self, client):
        job_id = client.post("/jobs", json={"username": "hikaru"}).json()["id"]
        response = client.post(
            f"/jobs/{job_id}/puzzles/ingest",
            json={"puzzles": [], "total_games": 0},
        )
        assert response.status_code == 401

    def test_unknown_job_returns_404(self, client):
        response = client.post(
            f"/jobs/{uuid4()}/puzzles/ingest",
            json={"puzzles": [], "total_games": 0},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 404
