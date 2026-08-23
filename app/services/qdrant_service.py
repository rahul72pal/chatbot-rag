from typing import Any, Dict, List, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, Filter, FieldCondition, MatchValue, FilterSelector, PayloadSchemaType
from langchain_qdrant import QdrantVectorStore
from langchain_core.embeddings import Embeddings
from app.core.config import get_settings
from app.core.logger import logger
from langchain_core.documents import Document
from app.core.context import current_user_id

class QdrantService:
    """Service wrapper for interacting with Qdrant Vector Store via LangChain with per-user DB configuration support."""

    def __init__(self, embeddings: Embeddings, mongo_db: Any = None):
        settings = get_settings()
        self.default_settings = settings
        self.mongo_db = mongo_db

        self.default_client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=120.0,
        )

        self.default_collection_name = settings.QDRANT_COLLECTION_NAME
        self.embeddings = embeddings
        self._vector_store = None

    async def get_user_qdrant_config(self, user_id: Optional[str] = None) -> Dict[str, str]:
        """Returns Qdrant credentials from environment settings."""
        return {
            "url": self.default_settings.QDRANT_URL,
            "api_key": self.default_settings.QDRANT_API_KEY,
            "collection_name": self.default_settings.QDRANT_COLLECTION_NAME
        }

    async def get_client_and_collection(self, user_id: Optional[str] = None):
        """Returns default QdrantClient instance and collection_name from environment settings."""
        return self.default_client, self.default_collection_name

    @property
    def client(self) -> QdrantClient:
        return self.default_client

    @property
    def collection_name(self) -> str:
        return self.default_collection_name

    @property
    def vector_store(self) -> QdrantVectorStore:
        if self._vector_store is None:
            self.create_collection_if_not_exists()
            self._vector_store = QdrantVectorStore(
                client=self.default_client,
                collection_name=self.default_collection_name,
                embedding=self.embeddings,
            )
        return self._vector_store

    def ensure_payload_indexes(self, client: Optional[QdrantClient] = None, collection_name: Optional[str] = None):
        """Ensures keyword payload indexes exist for metadata fields in Qdrant."""
        target_client = client or self.default_client
        target_collection = collection_name or self.default_collection_name
        fields = ["metadata.document_id", "metadata.chatbot_id", "metadata.user_id"]
        for field in fields:
            try:
                target_client.create_payload_index(
                    collection_name=target_collection,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD
                )
            except Exception:
                pass

    def create_collection_if_not_exists(self, client: Optional[QdrantClient] = None, collection_name: Optional[str] = None):
        """Creates the Qdrant collection and payload indexes if they do not already exist or if dimension mismatches."""
        target_client = client or self.default_client
        target_collection = collection_name or self.default_collection_name
        try:
            collections = target_client.get_collections()
            collection_info = None
            for col in collections.collections:
                if col.name == target_collection:
                    try:
                        collection_info = target_client.get_collection(target_collection)
                    except Exception:
                        pass
                    break

            vector_size = len(self.embeddings.embed_query("sample text"))

            if collection_info:
                current_size = getattr(getattr(collection_info.config, "params", None), "vectors", None)
                if current_size:
                    size_val = getattr(current_size, "size", None)
                    if size_val and size_val != vector_size:
                        logger.warning(f"Qdrant collection {target_collection} vector dimension mismatch (existing: {size_val}, current model: {vector_size}). Recreating collection...")
                        target_client.delete_collection(target_collection)
                        collection_info = None

            if not collection_info:
                logger.info(f"Creating collection {target_collection} in Qdrant with vector size {vector_size}...")
                target_client.create_collection(
                    collection_name=target_collection,
                    vectors_config=VectorParams(
                        size=vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Successfully created collection {target_collection} in Qdrant.")
            
            self.ensure_payload_indexes(client=target_client, collection_name=target_collection)
        except Exception as e:
            logger.error(f"Error checking or creating Qdrant collection: {e}")
            raise

    async def add_documents(self, documents: list, user_id: Optional[str] = None) -> list[str]:
        """Indexes LangChain Document objects in Qdrant in batches for target user."""
        import re
        
        cleaned_documents = []
        for doc in documents:
            content = doc.page_content or ""
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            content = re.sub(r'[ \t]+', ' ', content)
            content = re.sub(r'\n+', '\n', content)
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            cleaned_content = '\n'.join(lines)
            
            if cleaned_content.strip():
                cleaned_documents.append(
                    Document(
                        page_content=cleaned_content,
                        metadata=doc.metadata
                    )
                )
        
        if not cleaned_documents:
            return []
            
        target_user = user_id or (documents[0].metadata.get("user_id") if documents else None)
        client, collection_name = await self.get_client_and_collection(user_id=target_user)

        self.create_collection_if_not_exists(client=client, collection_name=collection_name)

        v_store = QdrantVectorStore(
            client=client,
            collection_name=collection_name,
            embedding=self.embeddings
        )

        batch_size = 40
        ids = []
        for i in range(0, len(cleaned_documents), batch_size):
            batch = cleaned_documents[i:i + batch_size]
            batch_ids = v_store.add_documents(batch)
            ids.extend(batch_ids)

        return ids

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        chatbot_id: str | None = None,
        user_id: str | None = None,
    ) -> List[Dict[str, Any]]:

        target_user = user_id or current_user_id.get(None)
        client, collection_name = await self.get_client_and_collection(user_id=target_user)

        query_vector = await self.embeddings.aembed_query(query)

        query_filter = None
        if chatbot_id or user_id:
            conditions = []
            if chatbot_id:
                conditions.append(FieldCondition(key="metadata.chatbot_id", match=MatchValue(value=chatbot_id)))
            elif user_id:
                conditions.append(FieldCondition(key="metadata.user_id", match=MatchValue(value=user_id)))
            query_filter = Filter(must=conditions)

        self.create_collection_if_not_exists(client=client, collection_name=collection_name)
        
        results = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )

        # Fallback 1: If chatbot_id filter returned no results, retry filtering by user_id
        if not results.points and chatbot_id and target_user:
            fallback_filter = Filter(must=[FieldCondition(key="metadata.user_id", match=MatchValue(value=target_user))])
            results = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
                query_filter=fallback_filter,
                with_payload=True,
            )

        # Fallback 2: If filtered search still returned 0 points, perform unfiltered search across collection
        if not results.points and query_filter is not None:
            results = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
                with_payload=True,
            )

        documents = []
        for result in results.points:
            payload = result.payload or {}
            doc = Document(
                page_content=payload.get("page_content", ""),
                metadata=payload.get("metadata", {}) or {},
            )
            documents.append({
                "text": doc.page_content,
                "score": result.score,
                "filename": doc.metadata.get("filename"),
                "document_id": doc.metadata.get("document_id") or str(result.id),
            })

        return documents

    async def delete_document_by_id(self, document_id: str, user_id: Optional[str] = None):
        """Deletes vector points matching metadata.document_id from Qdrant collection."""
        try:
            client, collection_name = await self.get_client_and_collection(user_id=user_id)
            self.ensure_payload_indexes(client=client, collection_name=collection_name)
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="metadata.document_id",
                        match=MatchValue(value=document_id)
                    )
                ]
            )
            client.delete(
                collection_name=collection_name,
                points_selector=FilterSelector(filter=query_filter)
            )
            logger.info(f"Successfully deleted vectors for document_id: {document_id} from Qdrant collection {collection_name}.")
        except Exception as e:
            logger.error(f"Error deleting vectors for document_id {document_id} from Qdrant: {e}")


# Instantiate module-level singleton for tool usage
from app.services.embedding_service import NvidiaEmbeddingService
qdrant_service = QdrantService(embeddings=NvidiaEmbeddingService())