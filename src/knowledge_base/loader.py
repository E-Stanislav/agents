from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.documents import Document

from src.config import settings
from src.knowledge_base.rag import KnowledgeBase

logger = logging.getLogger(__name__)


async def load_templates_into_kb(kb: KnowledgeBase) -> int:
    """Scan the templates/ directory and load all files into ChromaDB."""
    templates_dir = settings.templates_dir
    if not templates_dir.exists():
        logger.warning("Templates directory not found: %s", templates_dir)
        return 0

    documents: list[Document] = []
    for template_dir in templates_dir.iterdir():
        if not template_dir.is_dir():
            continue
        template_name = template_dir.name
        for file_path in template_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix in (".pyc", ".class", ".o"):
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel_path = file_path.relative_to(template_dir)
            documents.append(
                Document(
                    page_content=content,
                    metadata={
                        "type": "template",
                        "template_name": template_name,
                        "file_path": str(rel_path),
                        "language": file_path.suffix.lstrip("."),
                    },
                )
            )

    if documents:
        await kb.add_documents(documents)
        logger.info("Loaded %d template files from %s", len(documents), templates_dir)
    return len(documents)


async def load_custom_docs(kb: KnowledgeBase, docs_dir: Path) -> int:
    """Load custom documentation files (markdown) into the KB."""
    if not docs_dir.exists():
        return 0

    documents: list[Document] = []
    for md_file in docs_dir.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8", errors="replace")
        documents.append(
            Document(
                page_content=content,
                metadata={
                    "type": "documentation",
                    "source": str(md_file.relative_to(docs_dir)),
                },
            )
        )

    if documents:
        await kb.add_documents(documents)
        logger.info("Loaded %d documentation files", len(documents))
    return len(documents)
