from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import current_user
from app.research.index import BANK_DIRS, load_chunks
from app.research.registry import DOCUMENTS, DOCUMENTS_BY_ID, find_document_files
from app.research.search import search_bank_research

router = APIRouter(prefix="/research", tags=["Bank research"], dependencies=[Depends(current_user)])


@router.get("/documents")
def list_documents() -> dict[str, Any]:
    files, _ = find_document_files(BANK_DIRS)
    return {
        "items": [
            {
                "doc_id": document.doc_id,
                "title": document.title,
                "date": document.date,
                "topics": list(document.topics),
                "file_available": document.doc_id in files,
            }
            for document in DOCUMENTS
        ]
    }


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: str) -> FileResponse:
    """Original PDF for «перейти к первоисточнику»; open as <url>#page=N."""
    if doc_id not in DOCUMENTS_BY_ID:
        raise HTTPException(status_code=404, detail="Документ не найден")
    files, _ = find_document_files(BANK_DIRS)
    if doc_id not in files:
        raise HTTPException(status_code=404, detail="Файл документа не загружен на сервер")
    return FileResponse(files[doc_id], media_type="application/pdf", filename=f"{doc_id}.pdf")


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str) -> dict[str, Any]:
    chunk = next((item for item in load_chunks() if item.chunk_id == chunk_id), None)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Фрагмент не найден")
    return chunk.model_dump()


@router.get("/search")
def search(
    q: str = Query(min_length=2, max_length=300),
    channels: list[str] = Query(default=[]),
    top_k: int = Query(default=5, ge=1, le=10),
) -> dict[str, Any]:
    return {"items": search_bank_research(q, channels, top_k=top_k)}
