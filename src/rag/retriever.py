import logging

import chromadb
from langchain.retrievers import ContextualCompressionRetriever, EnsembleRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_chroma import Chroma
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class DataQualityRetriever:
    def __init__(self, chroma_host: str, chroma_port: int, embeddings) -> None:
        self.chroma_host = chroma_host
        self.chroma_port = chroma_port
        self.embeddings = embeddings
        self._retrievers: dict = {}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_retriever(self, collection_name: str):
        """Build BM25 + vector ensemble with cross-encoder reranking.

        Caches result (including None for empty/unavailable collections).
        Lazy — only called on first access per collection.
        """
        try:
            client = chromadb.HttpClient(host=self.chroma_host, port=self.chroma_port)
            collection = client.get_collection(collection_name)
            result = collection.get(include=["documents", "metadatas"])
        except Exception as e:
            logger.warning("Could not load collection %s: %s", collection_name, e)
            # Do not cache None — collection may become available after seeding
            return None

        raw_docs = result.get("documents") or []
        raw_metas = result.get("metadatas") or []

        if not raw_docs:
            logger.info("Collection %s is empty — retriever deferred", collection_name)
            # Do not cache None — collection may be seeded later without app restart
            return None

        lc_docs = [
            Document(page_content=text, metadata=meta or {})
            for text, meta in zip(raw_docs, raw_metas, strict=False)
        ]

        bm25 = BM25Retriever.from_documents(lc_docs)
        bm25.k = 10

        chroma_wrapper = Chroma(
            client=chromadb.HttpClient(host=self.chroma_host, port=self.chroma_port),
            collection_name=collection_name,
            embedding_function=self.embeddings,
        )
        vector_retriever = chroma_wrapper.as_retriever(search_kwargs={"k": 10})

        ensemble = EnsembleRetriever(
            retrievers=[vector_retriever, bm25],
            weights=[0.7, 0.3],
        )

        cross_encoder = HuggingFaceCrossEncoder(model_name=_CROSS_ENCODER_MODEL)
        compressor = CrossEncoderReranker(model=cross_encoder, top_n=5)
        compressed = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=ensemble,
        )

        self._retrievers[collection_name] = compressed
        return compressed

    def _get_retriever(self, collection_name: str):
        """Return cached retriever, building lazily on first call."""
        if collection_name not in self._retrievers:
            return self._build_retriever(collection_name)
        return self._retrievers[collection_name]

    def _filtered_search(
        self, collection_name: str, query: str, where: dict, k: int = 5
    ) -> list[Document]:
        """Direct Chroma similarity search with metadata filter (bypasses BM25)."""
        try:
            client = chromadb.HttpClient(host=self.chroma_host, port=self.chroma_port)
            chroma = Chroma(
                client=client,
                collection_name=collection_name,
                embedding_function=self.embeddings,
            )
            return chroma.similarity_search(query, k=k, filter=where)
        except Exception as e:
            logger.warning("Filtered search on %s failed: %s", collection_name, e)
            return []

    # ------------------------------------------------------------------
    # Public retrieve methods
    # ------------------------------------------------------------------

    def retrieve_similar_anomalies(
        self,
        query: str,
        anomaly_type: str | None = None,
        severity: str | None = None,
        days_lookback: int = 90,  # future: filter by detected_at window
    ) -> list[Document]:
        """Retrieve similar past anomalies from the anomaly_patterns collection."""
        where: dict = {}
        if anomaly_type:
            where["anomaly_type"] = {"$eq": anomaly_type}
        if severity:
            where["severity"] = {"$eq": severity}
        if where:
            return self._filtered_search("anomaly_patterns", query, where)
        retriever = self._get_retriever("anomaly_patterns")
        return retriever.invoke(query) if retriever else []

    def retrieve_playbook(self, query: str, anomaly_type: str) -> list[Document]:
        """Retrieve remediation playbooks applicable to the given anomaly type."""
        if anomaly_type:
            where = {"applicable_anomaly_types": {"$contains": anomaly_type}}
            return self._filtered_search("remediation_playbooks", query, where)
        retriever = self._get_retriever("remediation_playbooks")
        return retriever.invoke(query) if retriever else []

    def retrieve_business_context(self, table_name: str) -> list[Document]:
        """Retrieve business context metadata for a specific table."""
        where = {"table_name": {"$eq": table_name}}
        return self._filtered_search("business_context", table_name, where)

    def retrieve_dq_rules(self, table_name: str, rule_type: str | None = None) -> list[Document]:
        """Retrieve DQ rules that apply to a specific table or all tables ('*')."""
        base = {"$or": [{"applies_to": {"$eq": table_name}}, {"applies_to": {"$eq": "*"}}]}
        where = {"$and": [base, {"rule_type": {"$eq": rule_type}}]} if rule_type else base
        return self._filtered_search("dq_rules", table_name, where)
