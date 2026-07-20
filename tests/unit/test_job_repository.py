from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.models.job import Job, PENDING_STATUS, SEARCH_INDEX_REBUILD_JOB
from app.repositories.jobs import JobRepository

JOB_ID = UUID("c241dbf0-2d4e-4b91-9ad7-ce097a543bbd")


class FakeScalarResult:
    def __init__(self, one: Job | None = None) -> None:
        self.one = one

    def one_or_none(self) -> Job | None:
        return self.one


class FakeSession:
    def __init__(self, result: FakeScalarResult | None = None) -> None:
        self.result = result or FakeScalarResult()
        self.added: list[Job] = []
        self.flushed = False
        self.refreshed: list[Job] = []
        self.statements = []

    def add(self, instance: Job) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        self.flushed = True

    def refresh(self, instance: Job) -> None:
        self.refreshed.append(instance)

    def scalars(self, statement):
        self.statements.append(statement)
        return self.result


def compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_create_pending_adds_and_flushes_caller_owned_uuid():
    session = FakeSession()
    repository = JobRepository(session)

    job = repository.create_pending(
        JOB_ID,
        job_type=SEARCH_INDEX_REBUILD_JOB,
        progress_total=4,
        progress_message="Waiting for worker",
    )

    assert job.id == JOB_ID
    assert job.status == PENDING_STATUS
    assert job.progress_current == 0
    assert session.added == [job]
    assert session.flushed is True
    assert session.refreshed == [job]


def test_get_reads_job_by_uuid():
    expected = Job(id=JOB_ID, job_type=SEARCH_INDEX_REBUILD_JOB)
    session = FakeSession(FakeScalarResult(expected))

    assert JobRepository(session).get(JOB_ID) is expected
    assert f"jobs.id = '{JOB_ID}'" in compile_sql(session.statements[0])


def test_get_active_filters_by_type_and_nonterminal_states():
    expected = Job(id=JOB_ID, job_type=SEARCH_INDEX_REBUILD_JOB)
    session = FakeSession(FakeScalarResult(expected))

    assert JobRepository(session).get_active(SEARCH_INDEX_REBUILD_JOB) is expected
    sql = compile_sql(session.statements[0])
    assert "jobs.job_type = 'search_index_rebuild'" in sql
    assert "jobs.status IN ('PENDING', 'STARTED')" in sql


def test_claim_is_guarded_by_pending_status():
    session = FakeSession(FakeScalarResult(Job(id=JOB_ID)))

    JobRepository(session).claim(
        JOB_ID,
        progress_current=1,
        progress_total=4,
        progress_message="Loading documents",
    )

    sql = compile_sql(session.statements[0])
    assert f"jobs.id = '{JOB_ID}'" in sql
    assert "jobs.status = 'PENDING'" in sql
    assert "RETURNING" in sql


def test_progress_and_success_are_guarded_by_started_status():
    session = FakeSession(FakeScalarResult(Job(id=JOB_ID)))
    repository = JobRepository(session)

    repository.update_progress(
        JOB_ID,
        progress_current=2,
        progress_total=4,
        progress_message="Building search index",
    )
    repository.mark_success(
        JOB_ID,
        result={"index_version": f"redis-{JOB_ID}", "document_count": 2},
        progress_total=4,
        progress_message="Search index rebuilt",
    )

    progress = session.statements[0].compile(dialect=postgresql.dialect())
    success = session.statements[1].compile(dialect=postgresql.dialect())
    assert "STARTED" in progress.params.values()
    assert "STARTED" in success.params.values()


def test_failure_accepts_only_pending_or_started_jobs():
    session = FakeSession(FakeScalarResult(Job(id=JOB_ID)))

    JobRepository(session).mark_failure(
        JOB_ID,
        error="Search index rebuild failed.",
    )

    sql = compile_sql(session.statements[0])
    assert "jobs.status IN ('PENDING', 'STARTED')" in sql
