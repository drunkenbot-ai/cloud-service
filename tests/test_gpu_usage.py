"""GPU Farm usage-reporting contract tests."""
from __future__ import annotations

from app import crud
from app.db import SessionLocal

from .conftest import unique_email


def _key(quota: float) -> str:
    db = SessionLocal()
    try:
        account = crud.create_account(db, unique_email("gpu"), None, None)
        _, plaintext = crud.create_api_key(db, account.id, "test", quota)
        return plaintext
    finally:
        db.close()


def test_usage_report_is_idempotent_and_enforces_quota(client) -> None:
    key = _key(1.0)
    headers = {"Authorization": f"Bearer {key}"}
    payload = {"job_id": "job-report-1", "gpu_hours": 0.75, "gpu_count": 1}
    first = client.post("/auth/report-usage", json=payload, headers=headers)
    assert first.status_code == 200 and first.json()["accepted"] is True
    assert client.post("/auth/report-usage", json=payload, headers=headers).json()["accepted"] is True
    exhausted = client.post("/auth/report-usage", json={"job_id": "job-report-2", "gpu_hours": 0.5}, headers=headers).json()
    assert exhausted["accepted"] is False
    assert exhausted["reason"] == "GPU-hours quota exhausted."


def test_reservation_blocks_overdispatch_and_settles_actual_usage(client) -> None:
    key = _key(1.0)
    headers = {"Authorization": f"Bearer {key}"}
    reserve = client.post("/auth/reserve-usage", json={"job_id": "job-hold-1", "gpu_hours": 0.75}, headers=headers)
    assert reserve.status_code == 200 and reserve.json()["accepted"] is True
    # The active hold makes the remaining quarter-hour unavailable to a
    # second 0.5-hour dispatch, even though no job has completed yet.
    rejected = client.post("/auth/reserve-usage", json={"job_id": "job-hold-2", "gpu_hours": 0.5}, headers=headers).json()
    assert rejected["accepted"] is False
    assert rejected["reason"] == "GPU-hours quota exhausted."
    settled = client.post("/auth/report-usage", json={"job_id": "job-hold-1", "gpu_hours": 0.5}, headers=headers).json()
    assert settled["accepted"] is True
    # Settling a smaller actual usage releases the unused 0.25-hour hold.
    assert client.post("/auth/reserve-usage", json={"job_id": "job-hold-2", "gpu_hours": 0.5}, headers=headers).json()["accepted"] is True


def test_releasing_reservation_is_idempotent(client) -> None:
    key = _key(1.0)
    headers = {"Authorization": f"Bearer {key}"}
    assert client.post("/auth/reserve-usage", json={"job_id": "job-release", "gpu_hours": 1.0}, headers=headers).json()["accepted"] is True
    body = {"job_id": "job-release", "gpu_hours": 1.0}
    assert client.post("/auth/release-reservation", json=body, headers=headers).json()["accepted"] is True
    assert client.post("/auth/release-reservation", json=body, headers=headers).json()["accepted"] is True
    assert client.post("/auth/reserve-usage", json={"job_id": "job-new", "gpu_hours": 1.0}, headers=headers).json()["accepted"] is True
