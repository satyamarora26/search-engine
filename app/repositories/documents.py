from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document

ACTIVE_STATUS = "active"
DELETED_STATUS = "deleted"


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        title: str,
        content: str,
        url: str | None = None,
    ) -> Document:
        document = Document(
            title=title,
            content=content,
            url=url,
            status=ACTIVE_STATUS,
        )
        self.session.add(document)
        self.session.flush()
        self.session.refresh(document)
        return document

    def get_active(self, document_id: int) -> Document | None:
        statement = select(Document).where(
            Document.id == document_id,
            Document.status == ACTIVE_STATUS,
        )
        return self.session.scalars(statement).one_or_none()

    def list_active(self, *, limit: int = 100, offset: int = 0) -> list[Document]:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        if offset < 0:
            raise ValueError("offset cannot be negative.")

        statement = (
            select(Document)
            .where(Document.status == ACTIVE_STATUS)
            .order_by(Document.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(statement).all())

    def list_all_active(self) -> list[Document]:
        statement = (
            select(Document)
            .where(Document.status == ACTIVE_STATUS)
            .order_by(Document.id.asc())
        )
        return list(self.session.scalars(statement).all())

    def update_active(
        self,
        document_id: int,
        *,
        title: str,
        content: str,
        url: str | None,
    ) -> Document | None:
        document = self.get_active(document_id)
        if document is None:
            return None

        document.title = title
        document.content = content
        document.url = url
        self.session.flush()
        self.session.refresh(document)
        return document

    def soft_delete(self, document_id: int) -> Document | None:
        document = self.get_active(document_id)
        if document is None:
            return None

        document.status = DELETED_STATUS
        self.session.flush()
        self.session.refresh(document)
        return document
