from uuid import UUID

import pytest

from app.services.job_tracker import JobTracker, JobTransitionError

JOB_ID = UUID("c241dbf0-2d4e-4b91-9ad7-ce097a543bbd")


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeRepository:
    def __init__(self, session: FakeSession, result=object()) -> None:
        self.session = session
        self.result = result
        self.calls = []
        self.error: Exception | None = None

    def _call(self, name: str, **values):
        self.calls.append((name, values))
        if self.error:
            raise self.error
        return self.result

    def claim(self, job_id, **values):
        return self._call("claim", job_id=job_id, **values)

    def get(self, job_id):
        return self._call("get", job_id=job_id)

    def update_progress(self, job_id, **values):
        return self._call("update_progress", job_id=job_id, **values)

    def mark_success(self, job_id, **values):
        return self._call("mark_success", job_id=job_id, **values)

    def mark_failure(self, job_id, **values):
        return self._call("mark_failure", job_id=job_id, **values)


def build_tracker(repository_result=object()):
    sessions = []
    repositories = []

    def session_factory():
        session = FakeSession()
        sessions.append(session)
        return session

    def repository_factory(session):
        repository = FakeRepository(session, repository_result)
        repositories.append(repository)
        return repository

    return JobTracker(session_factory, repository_factory), sessions, repositories


def test_claim_commits_and_closes_a_short_session():
    tracker, sessions, repositories = build_tracker()

    claimed = tracker.claim(
        JOB_ID,
        progress_current=1,
        progress_total=4,
        progress_message="Loading documents",
    )

    assert claimed is True
    assert repositories[0].calls[0][0] == "claim"
    assert sessions[0].commits == 1
    assert sessions[0].rollbacks == 0
    assert sessions[0].closed is True


def test_get_job_reads_and_closes_without_committing():
    expected_job = object()
    tracker, sessions, repositories = build_tracker(
        repository_result=expected_job
    )

    job = tracker.get_job(JOB_ID)

    assert job is expected_job
    assert repositories[0].calls == [("get", {"job_id": JOB_ID})]
    assert sessions[0].commits == 0
    assert sessions[0].rollbacks == 0
    assert sessions[0].closed is True


def test_each_progress_update_uses_a_new_short_session():
    tracker, sessions, _ = build_tracker()

    tracker.update_progress(
        JOB_ID,
        progress_current=2,
        progress_total=4,
        progress_message="Building search index",
    )
    tracker.update_progress(
        JOB_ID,
        progress_current=3,
        progress_total=4,
        progress_message="Publishing search snapshot",
    )

    assert len(sessions) == 2
    assert all(session.commits == 1 for session in sessions)
    assert all(session.closed for session in sessions)


def test_rejected_required_progress_transition_raises_after_commit():
    tracker, sessions, _ = build_tracker(repository_result=None)

    with pytest.raises(JobTransitionError, match="progress"):
        tracker.update_progress(
            JOB_ID,
            progress_current=2,
            progress_total=4,
            progress_message="Building search index",
        )

    assert sessions[0].commits == 1
    assert sessions[0].closed is True


def test_repository_error_rolls_back_and_closes():
    tracker, sessions, repositories = build_tracker()

    def broken_repository_factory(session):
        repository = FakeRepository(session)
        repository.error = RuntimeError("database failed")
        repositories.append(repository)
        return repository

    tracker.repository_factory = broken_repository_factory

    with pytest.raises(RuntimeError, match="database failed"):
        tracker.mark_failure(JOB_ID, error="Search index rebuild failed.")

    assert sessions[0].rollbacks == 1
    assert sessions[0].closed is True


def test_mark_failure_reports_terminal_or_missing_job_without_raising():
    tracker, sessions, _ = build_tracker(repository_result=None)

    changed = tracker.mark_failure(
        JOB_ID,
        error="Search index rebuild failed.",
    )

    assert changed is False
    assert sessions[0].commits == 1
    assert sessions[0].closed is True
