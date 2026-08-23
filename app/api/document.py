import os
import shutil
import tempfile
from typing import Optional, List
from fastapi import APIRouter, Depends, UploadFile, File, Form, status, HTTPException, Query
from app.core.dependencies import get_document_service, get_current_user, get_chatbot_service
from app.services.document_service import DocumentService
from app.services.chatbot_service import ChatbotService
from app.schemas.document import DocumentResponse, DocumentListResponse
from app.core.logger import logger

router = APIRouter()

@router.post(
    "/document/upload",
    status_code=status.HTTP_200_OK,
    response_model=DocumentResponse,
    summary="Upload and embed a PDF document",
    description="Accepts a PDF document upload, stores metadata in MongoDB, embeds vector chunks in Qdrant."
)
async def upload_document(
    chatbot_id: str = Form(..., description="The ID of the chatbot to associate the document with."),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
    chatbot_service: ChatbotService = Depends(get_chatbot_service)
) -> dict:
    """Endpoint to upload a PDF file, index in Qdrant, and save record in MongoDB."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are currently supported."
        )

    user_id = current_user["id"]
    # Verify chatbot ownership
    chatbot = await chatbot_service.get_chatbot(chatbot_id=chatbot_id, user_id=user_id)
    if not chatbot or chatbot.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatbot not found or access denied."
        )

    # Enforce max 2 linked documents per chatbot limit
    existing_docs_count = await document_service.count_documents_by_chatbot(chatbot_id=chatbot_id)
    if existing_docs_count >= 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit reached: Each chatbot can only be linked to a maximum of 2 documents."
        )

    logger.info(f"Received document upload request for chatbot {chatbot_id} by user {user_id}: {file.filename}")

    # Calculate human-readable file size and validate 2 MB limit
    file_size_bytes = 0
    try:
        file.file.seek(0, os.SEEK_END)
        file_size_bytes = file.file.tell()
        file.file.seek(0)
    except Exception:
        pass

    MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB limit
    if file_size_bytes > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size ({file_size_bytes / (1024 * 1024):.1f} MB) exceeds the maximum allowed limit of 2 MB."
        )

    if file_size_bytes > 1024 * 1024:
        size_str = f"{file_size_bytes / (1024 * 1024):.1f} MB"
    elif file_size_bytes > 1024:
        size_str = f"{file_size_bytes / 1024:.0f} KB"
    else:
        size_str = f"{file_size_bytes} Bytes"

    # Create a temporary file to store the upload
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            shutil.copyfileobj(file.file, tmp)
            temp_file_path = tmp.name

        # Process document with metadata and save to MongoDB & Qdrant
        doc_record = await document_service.add_document(
            file_path=temp_file_path,
            user_id=user_id,
            chatbot_id=chatbot_id,
            filename=file.filename,
            size=size_str,
        )

        return doc_record
    except Exception as e:
        logger.exception(f"Error processing PDF upload {file.filename}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process PDF document: {str(e)}"
        )
    finally:
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up temp file {temp_file_path}: {cleanup_error}")

@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="Get user documents",
    description="Retrieves document metadata records for the current user, optionally filtered by chatbot_id."
)
async def get_documents(
    chatbot_id: Optional[str] = Query(None, description="Optional chatbot ID filter"),
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
) -> dict:
    user_id = current_user["id"]
    docs = await document_service.get_user_documents(user_id=user_id, chatbot_id=chatbot_id)
    return {"documents": docs}

@router.delete(
    "/document/{document_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete document",
    description="Deletes a document record from MongoDB and purges vector points from Qdrant."
)
async def delete_document(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
) -> dict:
    user_id = current_user["id"]
    success = await document_service.delete_document(document_id=document_id, user_id=user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied."
        )
    return {"success": True, "message": f"Document {document_id} and its vector embeddings deleted successfully."}
