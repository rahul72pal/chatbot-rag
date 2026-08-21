import pdf_inspector
from typing import Any, List, Dict, Optional
from datetime import datetime
from uuid import uuid4
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.services.qdrant_service import QdrantService
from app.core.logger import logger

class DocumentService:
    """Service to manage document records in MongoDB and vector embeddings in Qdrant."""

    def __init__(self, qdrant_service: QdrantService, mongo_db: Any = None):
        self.qdrant_service = qdrant_service
        self._collection = mongo_db["documents"] if mongo_db is not None else None
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100
        )

    def load_pdf_pages(self, file_path: str) -> list[Document]:
        """Loads pages of a PDF as LangChain Document objects using pdf-inspector."""
        result = pdf_inspector.extract_pages_markdown(file_path)
        return [
            Document(
                page_content=page_data.markdown or "",
                metadata={"source": file_path, "page": page_data.page},
            )
            for page_data in result.pages
        ]

    async def add_document(
        self,
        file_path: str,
        user_id: str,
        chatbot_id: str,
        filename: str,
        size: str,
    ) -> dict:
        """Loads a PDF, chunks it, indexes vectors in Qdrant, and stores document metadata in MongoDB."""
        doc_id = f"doc-{uuid4()}"

        # 1. Load document pages
        docs = self.load_pdf_pages(file_path)

        # 2. Add metadata
        metadata = {
            "filename": filename,
            "chatbot_id": chatbot_id,
            "user_id": user_id,
            "document_id": doc_id,
        }
        for doc in docs:
            doc.metadata.update(metadata)

        # 3. Chunk documents
        chunks = self.text_splitter.split_documents(docs)

        # 4. Store chunks in Qdrant Vector Store
        point_ids = await self.qdrant_service.add_documents(chunks, user_id=user_id)

        # 5. Store metadata record in MongoDB collection
        doc_record = {
            "_id": doc_id,
            "user_id": user_id,
            "chatbot_id": chatbot_id,
            "name": filename,
            "size": size,
            "status": "indexed",
            "chunks_count": len(chunks),
            "created_at": datetime.utcnow(),
        }

        if self._collection is not None:
            await self._collection.insert_one(doc_record)

        doc_record["id"] = doc_record.pop("_id")
        doc_record["point_ids"] = point_ids
        return doc_record

    async def get_user_documents(self, user_id: str, chatbot_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves document records belonging to a user, optionally filtered by chatbot_id."""
        if self._collection is None:
            return []

        query: Dict[str, Any] = {"user_id": user_id}
        if chatbot_id:
            query["chatbot_id"] = chatbot_id

        cursor = self._collection.find(query).sort("created_at", -1)
        documents = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            documents.append(doc)
        return documents

    async def delete_document(self, document_id: str, user_id: str) -> bool:
        """Deletes a document record from MongoDB and its associated vector embeddings from Qdrant."""
        if self._collection is None:
            return False

        # Find document to verify ownership
        doc = await self._collection.find_one({"_id": document_id, "user_id": user_id})
        if not doc:
            logger.warning(f"Document {document_id} not found or user {user_id} unauthorized")
            return False

        # 1. Delete vector points from Qdrant
        await self.qdrant_service.delete_document_by_id(document_id, user_id=user_id)

        # 2. Delete metadata document from MongoDB
        result = await self._collection.delete_one({"_id": document_id, "user_id": user_id})
        return result.deleted_count > 0