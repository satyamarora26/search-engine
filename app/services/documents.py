from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.repositories.documents import DocumentRepository

T = TypeVar("T")


class DocumentNotFoundError(Exception):
    pass


class DuplicateDocumentURLError(Exception):
    pass


class DocumentService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = DocumentRepository(session)

    def create_document(
        self,
        *,
        title: str,
        content: str,
        url: str | None = None,
    ) -> Document:
        return self._write(
            lambda: self.repository.create(title=title, content=content, url=url)
        )

    def list_documents(self, *, limit: int, offset: int) -> list[Document]:
        return self.repository.list_active(limit=limit, offset=offset)

    def get_document(self, document_id: int) -> Document:
        document = self.repository.get_active(document_id)
        if document is None:
            raise DocumentNotFoundError(f"Document {document_id} was not found.")
        return document

    def update_document(
        self,
        document_id: int,
        *,
        changes: dict,
    ) -> Document:
        current_document = self.repository.get_active(document_id)
        if current_document is None:
            raise DocumentNotFoundError(f"Document {document_id} was not found.")

        title = changes.get("title", current_document.title)
        content = changes.get("content", current_document.content)
        url = changes.get("url", current_document.url)

        return self._write(
            lambda: self._update_existing(
                document_id,
                title=title,
                content=content,
                url=url,
            )
        )

    def delete_document(self, document_id: int) -> None:
        def operation() -> None:
            document = self.repository.soft_delete(document_id)
            if document is None:
                raise DocumentNotFoundError(f"Document {document_id} was not found.")
            return None

        self._write(operation)

    def _update_existing(
        self,
        document_id: int,
        *,
        title: str,
        content: str,
        url: str | None,
    ) -> Document:
        document = self.repository.update_active(
            document_id,
            title=title,
            content=content,
            url=url,
        )
        if document is None:
            raise DocumentNotFoundError(f"Document {document_id} was not found.")
        return document

    def _write(self, operation: Callable[[], T]) -> T:
        try:
            result = operation()
            self.session.commit()
            return result
        except IntegrityError as error:
            self.session.rollback()
            raise DuplicateDocumentURLError("Document URL already exists.") from error
        except Exception:
            self.session.rollback()
            raise
