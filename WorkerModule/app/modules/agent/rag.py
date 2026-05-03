import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.documents import Document

try:
    from langchain_community.vectorstores import FAISS
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:
    FAISS = None
    HuggingFaceEmbeddings = None

from app.modules.worker.schemas import EVENT_SCHEMAS

logger = logging.getLogger(__name__)


class AgentKnowledgeBase:
    """FAISS-backed semantic search over Worker domain knowledge."""

    def __init__(self):
        self.vectorstore = None

    def build(self) -> None:
        """Load corpus documents and construct the FAISS index."""
        if FAISS is None or HuggingFaceEmbeddings is None:
            logger.warning("RAG dependencies not installed. Knowledge base disabled.")
            return

        documents = self._load_corpus()

        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        
        # Convert raw text chunks into LangChain Documents
        docs = [
            Document(page_content=d["content"], metadata=d.get("meta", {}))
            for d in documents
        ]
        
        self.vectorstore = FAISS.from_documents(docs, embeddings)
        logger.info("AgentKnowledgeBase built indexing %d documents.", len(docs))

    def search(self, query: str, k: int = 3) -> str:
        """Search the knowledge base and return formatted context."""
        if self.vectorstore is None:
            return "Knowledge base is disabled (missing dependencies or failed to build)."

        if not query or not query.strip():
            return "Query is empty."

        results = self.vectorstore.similarity_search(query, k=k)
        if not results:
            return "No relevant information found."

        formatted_results = []
        for i, doc in enumerate(results, start=1):
            source = doc.metadata.get("source", "Unknown Source")
            formatted_results.append(f"[{i}] From '{source}':\n{doc.page_content}")

        return "\n\n".join(formatted_results)

    def _load_corpus(self) -> List[Dict[str, Any]]:
        """Gather all documents to index: schemas, doc files."""
        corpus = []
        base_dir = Path(os.getcwd())

        # 1. Event Schemas
        for event_type, schema_dict in EVENT_SCHEMAS.items():
            # Convert Python types like <class 'str'> to 'string' for readability
            readable_schema = {}
            for k, v in schema_dict.items():
                if getattr(v, "__name__", None):
                    readable_schema[k] = v.__name__
                elif isinstance(v, dict):
                    readable_schema[k] = {ck: cv.__name__ if getattr(cv, "__name__", None) else str(cv) for ck, cv in v.items()}
                else:
                    readable_schema[k] = str(v)

            content = f"Event Schema for: {event_type}\nStructure:\n{readable_schema}"
            corpus.append({"content": content, "meta": {"source": f"Schema: {event_type}"}})

        # 2. (Removed Markdown Files - RAG now strictly indexes schemas)
        
        return corpus
