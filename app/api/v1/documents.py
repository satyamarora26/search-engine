from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.api.dependencies import get_bulk_ingestion_service
from app.db.session import get_db_session
from app.schemas.bulk_ingestion import (
    BulkDocumentsRequest,
    IngestionItemListResponse,
    IngestionItemResponse,
)
from app.schemas.documents import (
    DocumentCreateRequest,
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdateRequest,
)
from app.schemas.jobs import JobAcceptedResponse
from app.services.bulk_ingestion import (
    BulkIngestionNotFoundError,
    BulkIngestionService,
)
from app.services.documents import (
    DocumentNotFoundError,
    DocumentService,
    DuplicateDocumentURLError,
)
from app.services.jobs import (
    IndexJobConflictError,
    JobEnqueueError,
    JobStorageError,
)
from app.services.search_index import SearchIndexService, get_search_index_service

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_service(
    session: Session = Depends(get_db_session),
    search_index: SearchIndexService = Depends(get_search_index_service),
) -> DocumentService:
    return DocumentService(session, search_index)


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    payload: DocumentCreateRequest,
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    try:
        document = service.create_document(
            title=payload.title,
            content=payload.content,
            url=payload.url,
        )
    except DuplicateDocumentURLError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return DocumentResponse.model_validate(document)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    documents = service.list_documents(limit=limit, offset=offset)
    return DocumentListResponse(
        total_results=len(documents),
        limit=limit,
        offset=offset,
        documents=[
            DocumentResponse.model_validate(document)
            for document in documents
        ],
    )


@router.post(
    "/bulk",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def bulk_create_documents(
    payload: BulkDocumentsRequest,
    service: BulkIngestionService = Depends(get_bulk_ingestion_service),
) -> JobAcceptedResponse:
    try:
        job = service.enqueue_documents(payload.documents)
    except IndexJobConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(error),
                "active_job_id": str(error.active_job.id),
                "status_url": f"/api/v1/jobs/{error.active_job.id}",
            },
        ) from error
    except (JobEnqueueError, JobStorageError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    return JobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        status_url=f"/api/v1/jobs/{job.id}",
    )


@router.get(
    "/bulk/{job_id}/items",
    response_model=IngestionItemListResponse,
)
def list_bulk_ingestion_items(
    job_id: UUID,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: BulkIngestionService = Depends(get_bulk_ingestion_service),
) -> IngestionItemListResponse:
    try:
        total, items = service.list_items(
            job_id,
            limit=limit,
            offset=offset,
        )
    except BulkIngestionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except JobStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    return IngestionItemListResponse(
        job_id=job_id,
        total_results=total,
        limit=limit,
        offset=offset,
        items=[IngestionItemResponse.model_validate(item) for item in items],
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int = Path(..., ge=1),
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    try:
        document = service.get_document(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return DocumentResponse.model_validate(document)


@router.patch("/{document_id}", response_model=DocumentResponse)
def update_document(
    payload: DocumentUpdateRequest,
    document_id: int = Path(..., ge=1),
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    try:
        document = service.update_document(document_id, changes=payload.changes())
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DuplicateDocumentURLError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int = Path(..., ge=1),
    service: DocumentService = Depends(get_document_service),
) -> Response:
    try:
        service.delete_document(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
