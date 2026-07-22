import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useState } from 'react'

import { getDocument, listDocuments } from '../api/client'
import type { Document, DocumentListResponse } from '../api/types'
import { DocumentDetail } from '../components/DocumentDetail'
import { DocumentList } from '../components/DocumentList'
import { Panel } from '../components/Panel'

const PAGE_SIZE = 20

function requestErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The document request could not be completed.'
}

export function LibraryPage() {
  const [offset, setOffset] = useState(0)
  const [listRequest, setListRequest] = useState(0)
  const [listResponse, setListResponse] = useState<DocumentListResponse | null>(null)
  const [isLoadingList, setIsLoadingList] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [selectedDocumentId, setSelectedDocumentId] = useState<number | null>(null)
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null)
  const [isLoadingDetail, setIsLoadingDetail] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setIsLoadingList(true)
    setListError(null)

    listDocuments(PAGE_SIZE, offset)
      .then((response) => {
        if (cancelled) return
        setListResponse(response)
        setIsLoadingList(false)
      })
      .catch((error) => {
        if (cancelled) return
        setListError(requestErrorMessage(error))
        setIsLoadingList(false)
      })

    return () => {
      cancelled = true
    }
  }, [listRequest, offset])

  function selectDocument(documentId: number) {
    setSelectedDocumentId(documentId)
    setSelectedDocument(null)
    setDetailError(null)
    setIsLoadingDetail(true)

    getDocument(documentId)
      .then((document) => {
        setSelectedDocument(document)
        setIsLoadingDetail(false)
      })
      .catch((error) => {
        setDetailError(requestErrorMessage(error))
        setIsLoadingDetail(false)
      })
  }

  function retryDocument() {
    if (selectedDocumentId !== null) selectDocument(selectedDocumentId)
  }

  function changePage(nextOffset: number) {
    setOffset(nextOffset)
    setSelectedDocumentId(null)
    setSelectedDocument(null)
    setDetailError(null)
  }

  const documents = listResponse?.documents ?? null
  const pageNumber = Math.floor(offset / PAGE_SIZE) + 1
  const canGoNext = Boolean(documents && documents.length >= PAGE_SIZE && !isLoadingList)

  return (
    <>
      <section className="page-intro" aria-labelledby="library-title">
        <p className="page-eyebrow">Document library</p>
        <h1 id="library-title">Everything your index has kept.</h1>
        <p className="page-copy">Browse the searchable corpus and inspect the source behind each result.</p>
      </section>

      <div className="library-grid">
        <Panel className="library-list-panel" eyebrow="Indexed corpus" title="Stored documents" action={<span className="library-page-label">Page {pageNumber}</span>}>
          <DocumentList
            documents={documents}
            error={listError}
            isLoading={isLoadingList}
            onRetry={() => setListRequest((current) => current + 1)}
            onSelect={selectDocument}
            selectedDocumentId={selectedDocumentId}
          />
          <div className="library-pagination" aria-label="Document pagination">
            <span>{documents?.length ?? 0} documents on this page</span>
            <div>
              <button className="button button-quiet" type="button" aria-label="Previous page" disabled={offset === 0 || isLoadingList} onClick={() => changePage(Math.max(0, offset - PAGE_SIZE))}>
                <ChevronLeft size={15} aria-hidden="true" />
                Previous
              </button>
              <button className="button button-quiet" type="button" aria-label="Next page" disabled={!canGoNext} onClick={() => changePage(offset + PAGE_SIZE)}>
                Next
                <ChevronRight size={15} aria-hidden="true" />
              </button>
            </div>
          </div>
        </Panel>

        <Panel className="library-detail-panel" eyebrow="Selected source" title="Document detail">
          <DocumentDetail
            document={selectedDocument}
            error={detailError}
            isLoading={isLoadingDetail}
            onRetry={retryDocument}
            selectedDocumentId={selectedDocumentId}
          />
        </Panel>
      </div>
    </>
  )
}
