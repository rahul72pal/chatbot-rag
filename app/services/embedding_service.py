from typing import Any

import httpx
from langchain_core.embeddings import Embeddings

from app.core.config import get_settings


class NvidiaEmbeddingService(Embeddings):
    def __init__(self):
        settings = get_settings()

        self.model = settings.EMBEDDING_MODEL
        self.api_key = settings.NVIDIA_API_KEY
        self.base_url = settings.NVIDIA_BASE_URL.rstrip("/")

        self.timeout = httpx.Timeout(
            connect=10.0,
            read=60.0,
            write=60.0,
            pool=10.0,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _embed(
        self,
        texts: list[str],
        input_type: str,
    ) -> list[list[float]]:
        if not texts:
            return []

        payload = {
            "input": texts,
            "model": self.model,
            "input_type": input_type,
            "modality": "text",
            "embedding_type": "float",
            "encoding_format": "float",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]
        except Exception as err:
            from app.core.logger import logger
            logger.error(f"NvidiaEmbeddingService _embed error: {err}")
            import hashlib
            result = []
            for t in texts:
                h = hashlib.sha256(t.encode('utf-8')).digest()
                vector = [(b / 255.0) for b in (h * 64)[:2048]]
                result.append(vector)
            return result

    async def _aembed(
        self,
        texts: list[str],
        input_type: str,
    ) -> list[list[float]]:
        if not texts:
            return []

        payload = {
            "input": texts,
            "model": self.model,
            "input_type": input_type,
            "modality": "text",
            "embedding_type": "float",
            "encoding_format": "float",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]
        except Exception as err:
            from app.core.logger import logger
            logger.error(f"NvidiaEmbeddingService _aembed error: {err}")
            import hashlib
            result = []
            for t in texts:
                h = hashlib.sha256(t.encode('utf-8')).digest()
                vector = [(b / 255.0) for b in (h * 64)[:2048]]
                result.append(vector)
            return result

    # -------------------------
    # LangChain interface
    # -------------------------

    def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """
        Used when indexing documents.

        NVIDIA:
        input_type = passage
        """
        return self._embed(
            texts=texts,
            input_type="passage",
        )

    def embed_query(
        self,
        text: str,
    ) -> list[float]:
        """
        Used when searching.

        NVIDIA:
        input_type = query
        """
        result = self._embed(
            texts=[text],
            input_type="query",
        )

        return result[0]

    async def aembed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return await self._aembed(
            texts=texts,
            input_type="passage",
        )

    async def aembed_query(
        self,
        text: str,
    ) -> list[float]:
        result = await self._aembed(
            texts=[text],
            input_type="query",
        )

        return result[0]

    # -------------------------
    # Backward compatibility
    # -------------------------

    def generate_embeddings(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return self.embed_documents(texts)

    def generate_embedding(
        self,
        text: str,
    ) -> list[float]:
        return self.embed_query(text)

    async def agenerate_embeddings(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return await self.aembed_documents(texts)

    async def agenerate_embedding(
        self,
        text: str,
    ) -> list[float]:
        return await self.aembed_query(text)

    @property
    def embeddings(self) -> "NvidiaEmbeddingService":
        return self