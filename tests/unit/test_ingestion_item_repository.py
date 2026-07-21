from importlib import import_module
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.models.ingestion_item import (
    FAILED_ITEM_STATUS,
    IMPORTED_ITEM_STATUS,
    PENDING_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    IngestionItem,
)

JOB_ID = UUID("57d89fd9-4b92-468c-8cc4-640ce73ec4f1")


def repository_type():
    return import_module(
        "app.repositories.ingestion_items"
    ).IngestionItemRepository


class FakeScalarResult:
    def __init__(
        self,
        one: IngestionItem | None = None,
        all_: list | None = None,
    ) -> None:
        self._one = one
        self._all = all_ if all_ is not None else []

    def one_or_none(self):
        return self._one

    def all(self):
        return self._all


class FakeExecuteResult:
    def __init__(self, rows: list[tuple[str, int]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[str, int]]:
        return self.rows


class FakeSession:
    def __init__(
        self,
        *,
        scalar_result: FakeScalarResult | None = None,
        scalar_value: int | None = None,
        execute_rows: list[tuple[str, int]] | None = None,
    ) -> None:
        self.scalar_result = scalar_result or FakeScalarResult()
        self.scalar_value = scalar_value
        self.execute_rows = execute_rows or []
        self.added: list[IngestionItem] = []
        self.flushed = False
        self.statements = []

    def add(self, instance: IngestionItem) -> None:
        self.added.append(instance)

    def add_all(self, instances: list[IngestionItem]) -> None:
        self.added.extend(instances)

    def flush(self) -> None:
        self.flushed = True

    def scalars(self, statement):
        self.statements.append(statement)
        return self.scalar_result

    def scalar(self, statement):
        self.statements.append(statement)
        return self.scalar_value

    def execute(self, statement):
        self.statements.append(statement)
        return FakeExecuteResult(self.execute_rows)


def compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_stage_many_preserves_zero_based_positions_and_raw_payloads():
    session = FakeSession()
    repository = repository_type()(session)

    items = repository.stage_many(JOB_ID, [{"title": "One"}, 42, None])

    assert [(item.position, item.payload) for item in items] == [
        (0, {"title": "One"}),
        (1, 42),
        (2, None),
    ]
    assert all(item.job_id == JOB_ID for item in items)
    assert all(item.status == PENDING_ITEM_STATUS for item in items)
    assert session.added == items
    assert session.flushed is True


def test_stage_at_position_preserves_crawler_discovery_position():
    session = FakeSession()
    repository = repository_type()(session)

    item = repository.stage_at_position(
        JOB_ID,
        17,
        {"title": "BM25", "content": "ranking"},
    )

    assert item.job_id == JOB_ID
    assert item.position == 17
    assert item.status == PENDING_ITEM_STATUS
    assert session.added == [item]
    assert session.flushed is True


def test_get_for_update_locks_one_item():
    expected = IngestionItem(id=10, job_id=JOB_ID, position=0, payload={})
    session = FakeSession(scalar_result=FakeScalarResult(one=expected))

    assert repository_type()(session).get_for_update(10) is expected
    sql = compile_sql(session.statements[0])
    assert "ingestion_items.id = 10" in sql
    assert "FOR UPDATE" in sql


def test_pending_ids_filter_and_use_stable_position_order():
    session = FakeSession(scalar_result=FakeScalarResult(all_=[7, 9]))

    assert repository_type()(session).list_pending_ids(JOB_ID) == [7, 9]
    sql = compile_sql(session.statements[0])
    assert f"ingestion_items.job_id = '{JOB_ID}'" in sql
    assert "ingestion_items.status = 'pending'" in sql
    assert "ORDER BY ingestion_items.position ASC" in sql


@pytest.mark.parametrize(
    ("method", "values"),
    [
        ("mark_imported", {"document_id": 81}),
        ("mark_skipped", {"error": "duplicate_url"}),
        ("mark_failed", {"error": "content: Field required"}),
    ],
)
def test_outcome_updates_are_guarded_by_pending_status(method, values):
    expected = IngestionItem(id=10, job_id=JOB_ID, position=0, payload={})
    session = FakeSession(scalar_result=FakeScalarResult(one=expected))
    repository = repository_type()(session)

    assert getattr(repository, method)(10, **values) is expected
    sql = compile_sql(session.statements[0])
    assert "ingestion_items.id = 10" in sql
    assert "ingestion_items.status = 'pending'" in sql
    assert "RETURNING" in sql


def test_counts_fill_missing_status_groups_with_zero():
    session = FakeSession(
        execute_rows=[
            (PENDING_ITEM_STATUS, 1),
            (IMPORTED_ITEM_STATUS, 2),
            (SKIPPED_ITEM_STATUS, 3),
        ]
    )

    counts = repository_type()(session).counts(JOB_ID)

    assert counts.received == 6
    assert counts.imported == 2
    assert counts.skipped == 3
    assert counts.failed == 0


def test_terminal_and_total_counts_use_database_counts():
    terminal_session = FakeSession(scalar_value=2)
    total_session = FakeSession(scalar_value=5)

    assert repository_type()(terminal_session).count_terminal(JOB_ID) == 2
    assert repository_type()(total_session).count_for_job(JOB_ID) == 5
    terminal_sql = compile_sql(terminal_session.statements[0])
    assert "ingestion_items.status IN" in terminal_sql


def test_list_for_job_applies_stable_pagination():
    expected = [
        IngestionItem(id=1, job_id=JOB_ID, position=0, payload={}),
        IngestionItem(id=2, job_id=JOB_ID, position=1, payload={}),
    ]
    session = FakeSession(scalar_result=FakeScalarResult(all_=expected))

    assert repository_type()(session).list_for_job(
        JOB_ID, limit=25, offset=50
    ) == expected
    sql = compile_sql(session.statements[0])
    assert "ORDER BY ingestion_items.position ASC" in sql
    assert "LIMIT 25" in sql
    assert "OFFSET 50" in sql


def test_list_for_job_rejects_invalid_pagination_without_sql():
    session = FakeSession()
    repository = repository_type()(session)

    with pytest.raises(ValueError, match="limit must be at least 1"):
        repository.list_for_job(JOB_ID, limit=0, offset=0)
    with pytest.raises(ValueError, match="offset cannot be negative"):
        repository.list_for_job(JOB_ID, limit=1, offset=-1)

    assert session.statements == []
