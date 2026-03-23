from __future__ import annotations

import logging
from typing import Optional

from langchain_core.documents import Document

from src.config import settings

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """RAG knowledge base backed by ChromaDB.

    Stores project templates, framework documentation, and best-practice
    snippets. Agents query it via similarity search to get relevant
    context for code generation.
    """

    def __init__(self) -> None:
        self._vectorstore = None
        self._collection_name = "project_knowledge"

    def _get_vectorstore(self):
        if self._vectorstore is not None:
            return self._vectorstore

        from langchain_chroma import Chroma
        from src.llm import registry

        embedding = registry.get_embedding_model()
        self._vectorstore = Chroma(
            collection_name=self._collection_name,
            embedding_function=embedding,
            collection_metadata={"hnsw:space": "cosine"},
        )
        return self._vectorstore

    async def search(
        self,
        query: str,
        k: int = 5,
        filter_metadata: Optional[dict] = None,
    ) -> list[Document]:
        """Search for relevant documents by semantic similarity."""
        vs = self._get_vectorstore()
        kwargs = {"k": k}
        if filter_metadata:
            kwargs["filter"] = filter_metadata
        results = vs.similarity_search(query, **kwargs)
        logger.info("KB search '%s' returned %d results", query[:50], len(results))
        return results

    async def search_templates(self, project_type: str, tech_stack: list[str]) -> list[Document]:
        """Search for project templates matching the given stack."""
        query = f"project template for {project_type} using {', '.join(tech_stack)}"
        return await self.search(query, k=3, filter_metadata={"type": "template"})

    async def search_docs(self, technology: str, topic: str) -> list[Document]:
        """Search for documentation on a specific technology/topic."""
        query = f"{technology} {topic} documentation best practices"
        return await self.search(query, k=5, filter_metadata={"type": "documentation"})

    async def add_documents(self, documents: list[Document]) -> None:
        """Add documents to the knowledge base."""
        vs = self._get_vectorstore()
        vs.add_documents(documents)
        logger.info("Added %d documents to knowledge base", len(documents))
