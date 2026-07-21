from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.ingestion_item import PENDING_ITEM_STATUS, IngestionItem
from app.repositories.documents import DocumentRepository
from app.repositories.ingestion_items import IngestionItemRepository
from app.schemas.bulk_ingestion import (
    BulkDocumentInput,
    format_item_validation_error,
)


@dataclass(frozen=True)
class IngestionOutcome:
    position: int
    status: str
    document_id: int | None
    error: str | None

    @classmethod
    def from_item(cls, item: IngestionItem) -> "IngestionOutcome":
        return cls(
            position=item.position,
            status=item.status,
            document_id=item.document_id,
            error=item.error,
        )


class IngestionItemNotFoundError(Exception):
    pass


class IngestionItemProcessor:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        item_repository_factory: Callable[
            [Session], IngestionItemRepository
        ] = IngestionItemRepository,
        document_repository_factory: Callable[
            [Session], DocumentRepository
        ] = DocumentRepository,
    ) -> None:
        self.session_factory = session_factory
        self.item_repository_factory = item_repository_factory
        self.document_repository_factory = document_repository_factory

    def process(self, item_id: int) -> IngestionOutcome:
        session = self.session_factory()
        try:
            items = self.item_repository_factory(session)
            item = items.get_for_update(item_id)
            if item is None:
                raise IngestionItemNotFoundError(
                    f"Ingestion item {item_id} was not found."
                )
            if item.status != PENDING_ITEM_STATUS:
                return IngestionOutcome.from_item(item)

            try:
                payload = BulkDocumentInput.model_validate(item.payload)
            except ValidationError as error:
                updated = items.mark_failed(
                    item.id,
                    error=format_item_validation_error(error),
                )
            else:
                try:
                    with session.begin_nested():
                        document = self.document_repository_factory(
                            session
                        ).create(
                            title=payload.title,
                            content=payload.content,
                            url=payload.url,
                        )
                except IntegrityError as error:
                    if constraint_name(error) == "documents_url_key":
                        updated = items.mark_skipped(
                            item.id,
                            error="duplicate_url",
                        )
                    else:
                        updated = items.mark_failed(
                            item.id,
                            error="document_integrity_error",
                        )
                else:
                    updated = items.mark_imported(
                        item.id,
                        document_id=document.id,
                    )

            if updated is None:
                raise RuntimeError(
                    "Pending ingestion item rejected its outcome."
                )
            session.commit()
            return IngestionOutcome.from_item(updated)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return name if isinstance(name, str) else None
