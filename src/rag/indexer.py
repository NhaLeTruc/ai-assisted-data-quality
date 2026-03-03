import logging

import chromadb
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.core.schema import Document as LlamaDocument
from llama_index.embeddings.openai import OpenAIEmbedding

logger = logging.getLogger(__name__)

_COLLECTIONS = ["anomaly_patterns", "dq_rules", "remediation_playbooks", "business_context"]


class DataQualityIndexer:
    def __init__(self, chroma_host: str, chroma_port: int) -> None:
        self.chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        self.embed_model = OpenAIEmbedding(model="text-embedding-3-large")
        self.splitter = SemanticSplitterNodeParser(
            buffer_size=1,
            breakpoint_percentile_threshold=95,
            embed_model=self.embed_model,
        )

    @staticmethod
    def lists_to_strings(metadata: dict) -> dict:
        """Convert list values to comma-joined strings (Chroma metadata constraint)."""
        result = {}
        for k, v in metadata.items():
            if isinstance(v, list):
                result[k] = ", ".join(str(x) for x in v)
            elif v is None:
                result[k] = ""
            else:
                result[k] = v
        return result

    def index_documents(self, collection_name: str, documents: list) -> int:
        """Chunk via SemanticSplitter, embed with OpenAI, and upsert into Chroma.

        Each document must have "id", "content", and optionally "metadata".
        Returns the number of source documents indexed (not chunk count).
        """
        collection = self.chroma_client.get_or_create_collection(collection_name)
        for doc in documents:
            doc_id: str = doc["id"]
            content: str = doc["content"]
            metadata: dict = self.lists_to_strings(doc.get("metadata", {}))

            # Semantic chunking via LlamaIndex
            llama_doc = LlamaDocument(text=content, doc_id=doc_id)
            nodes = self.splitter.get_nodes_from_documents([llama_doc])

            if nodes:
                texts = [n.get_content() for n in nodes]
                chunk_ids = [
                    f"{doc_id}_chunk_{i}" if len(nodes) > 1 else doc_id for i in range(len(nodes))
                ]
                chunk_metas = [
                    {**metadata, "source_doc_id": doc_id, "chunk_index": i}
                    for i in range(len(nodes))
                ]
            else:
                texts = [content]
                chunk_ids = [doc_id]
                chunk_metas = [metadata]

            # Explicit embeddings so Chroma stores OpenAI vectors (not default model)
            embeddings_list = self.embed_model.get_text_embedding_batch(texts)
            collection.upsert(
                ids=chunk_ids,
                documents=texts,
                embeddings=embeddings_list,
                metadatas=chunk_metas,
            )
            logger.debug("Indexed %s into %s (%d chunk(s))", doc_id, collection_name, len(texts))
        return len(documents)

    def upsert_document(
        self, collection_name: str, doc_id: str, content: str, metadata: dict
    ) -> None:
        """Upsert a single document (no chunking)."""
        collection = self.chroma_client.get_or_create_collection(collection_name)
        clean_meta = self.lists_to_strings(metadata)
        embedding = self.embed_model.get_text_embedding(content)
        collection.upsert(
            ids=[doc_id],
            documents=[content],
            embeddings=[embedding],
            metadatas=[clean_meta],
        )

    def get_collection_stats(self) -> dict:
        """Return {collection_name: document_count} for all 4 standard collections."""
        stats: dict = {}
        for name in _COLLECTIONS:
            try:
                stats[name] = self.chroma_client.get_collection(name).count()
            except Exception:
                stats[name] = 0
        return stats
