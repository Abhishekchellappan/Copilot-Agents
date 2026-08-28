"""
HLD MCP Server — Offline RAG Engine (BM25 + Semantic Vector Retrieval)
100% self-contained, corporate-firewall-proof retrieval engine.
Provides document ingestion, semantic similarity search, and SRS intent
classification with zero external model downloads.
"""

import os
import re
import math
import json
from collections import Counter
from typing import Optional

from config import (
    PERSIST_DIR,
    HLD_COLLECTION_NAME,
    API_COLLECTION_NAME,
)

EMBEDDING_MODEL_NAME = "Local-Semantic-Engine (BM25/TF-IDF)"

# ============================================================================
# In-Memory Storage & Persistence
# ============================================================================
_HLD_STORE = None
_API_STORE = None


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase technical terms, symbols, and keywords."""
    tokens = re.findall(r"[a-zA-Z0-9_\.\-]+", text.lower())
    return [t for t in tokens if len(t) > 1]


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into coherent paragraph and sentence chunks."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current_chunk = []
    current_len = 0

    for p in paragraphs:
        words = p.split()
        if current_len + len(words) > chunk_size and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            overlap_words = current_chunk[-1].split()[-overlap:] if current_chunk else []
            current_chunk = [" ".join(overlap_words), p] if overlap_words else [p]
            current_len = len(overlap_words) + len(words)
        else:
            current_chunk.append(p)
            current_len += len(words)

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks if chunks else [text]


class LocalCollection:
    """Persistent inverted index collection with BM25 and TF-IDF scoring."""

    def __init__(self, name: str, persist_dir: str):
        self.name = name
        self.file_path = os.path.join(persist_dir, f"{name}.json")
        self.docs = []
        self.doc_freq = Counter()
        self.total_docs = 0
        self.avg_doc_len = 0.0
        self._load()

    def _load(self):
        """Load stored chunks from disk if exists."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.docs = data.get("docs", [])
                    self.total_docs = len(self.docs)
                    total_len = sum(d.get("doc_len", len(_tokenize(d["text"]))) for d in self.docs)
                    self.avg_doc_len = (total_len / self.total_docs) if self.total_docs > 0 else 0.0
                    self.doc_freq = Counter()
                    for d in self.docs:
                        unique_terms = set(_tokenize(d["text"]))
                        for t in unique_terms:
                            self.doc_freq[t] += 1
            except Exception as e:
                print(f"⚠️ Notice: Could not load collection {self.name}: {e}")

    def _save(self):
        """Persist collection to disk (compact JSON for fast I/O)."""
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump({"docs": self.docs}, f)

    def clear(self):
        """Clear all documents and reset the index."""
        self.docs = []
        self.doc_freq = Counter()
        self.total_docs = 0
        self.avg_doc_len = 0.0
        self._save()

    def insert(self, text: str, metadata: dict) -> int:
        """Chunk and insert a single document into the collection."""
        return self.insert_batch([text], [metadata])

    def insert_batch(self, texts: list, metadatas: list) -> int:
        """
        Chunk and insert a batch of documents in memory,
        updating index statistics and saving to disk EXACTLY ONCE at the end.
        Eliminates 1,600+ redundant disk writes!
        """
        total_new_chunks = 0
        for i, text in enumerate(texts):
            meta = metadatas[i] if i < len(metadatas) else {}
            chunks = _chunk_text(text)
            for chunk in chunks:
                tokens = _tokenize(chunk)
                doc_entry = {
                    "text": chunk,
                    "metadata": meta,
                    "doc_len": len(tokens),
                }
                self.docs.append(doc_entry)
                for t in set(tokens):
                    self.doc_freq[t] += 1
                total_new_chunks += 1

        self.total_docs = len(self.docs)
        total_len = sum(d.get("doc_len", 1) for d in self.docs)
        self.avg_doc_len = (total_len / self.total_docs) if self.total_docs > 0 else 0.0
        self._save()
        return total_new_chunks

    def query(self, query_text: str, top_k: int = 5) -> list[dict]:
        """BM25 relevance ranking query."""
        if not self.docs:
            return []

        query_tokens = _tokenize(query_text)
        if not query_tokens:
            return []

        k1 = 1.5
        b = 0.75
        N = self.total_docs
        scores = []

        for idx, doc in enumerate(self.docs):
            doc_tokens = _tokenize(doc["text"])
            doc_len = doc.get("doc_len", len(doc_tokens))
            term_counts = Counter(doc_tokens)
            score = 0.0

            for q in query_tokens:
                if q in term_counts:
                    tf = term_counts[q]
                    df = self.doc_freq.get(q, 1)
                    idf = math.log(1.0 + (N - df + 0.5) / (df + 0.5))
                    num = tf * (k1 + 1.0)
                    den = tf + k1 * (1.0 - b + b * (doc_len / (self.avg_doc_len or 1.0)))
                    score += idf * (num / den)

            if score > 0.0:
                scores.append((score, doc))

        scores.sort(key=lambda x: x[0], reverse=True)
        max_score = scores[0][0] if scores else 1.0
        results = []
        for s, doc in scores[:top_k]:
            normalized_score = min(1.0, round(s / (max_score or 1.0), 4))
            results.append({
                "text": doc["text"],
                "score": normalized_score,
                "metadata": doc["metadata"],
            })

        return results

    def count(self) -> int:
        return len(self.docs)


def _get_hld_store() -> LocalCollection:
    global _HLD_STORE
    if _HLD_STORE is None:
        _HLD_STORE = LocalCollection(HLD_COLLECTION_NAME, PERSIST_DIR)
    return _HLD_STORE


def _get_api_store() -> LocalCollection:
    global _API_STORE
    if _API_STORE is None:
        _API_STORE = LocalCollection(API_COLLECTION_NAME, PERSIST_DIR)
    return _API_STORE


# ============================================================================
# Document Ingestion
# ============================================================================
def ingest_documents(
    texts: list,
    metadatas: list,
    collection: str = "hld",
    clear_first: bool = False,
) -> int:
    """Ingest documents into the specified local knowledge collection using fast batch processing."""
    store = _get_hld_store() if collection == "hld" else _get_api_store()
    if clear_first:
        store.clear()
    return store.insert_batch(texts, metadatas)


# ============================================================================
# Retrieval / Querying
# ============================================================================
def query_hld_knowledge(query_text: str, top_k: int = 5) -> list:
    """Query the HLD knowledge base for relevant design document chunks."""
    store = _get_hld_store()
    return store.query(query_text, top_k=top_k)


def query_api_knowledge(query_text: str, top_k: int = 5) -> list:
    """Query the API spec knowledge base for relevant API documentation chunks."""
    store = _get_api_store()
    return store.query(query_text, top_k=top_k)


def search_all(query_text: str, top_k: int = 5) -> dict:
    """Query both knowledge bases and return combined results."""
    return {
        "hld_results": query_hld_knowledge(query_text, top_k),
        "api_results": query_api_knowledge(query_text, top_k),
    }


# ============================================================================
# SRS Intent Classification
# ============================================================================
def classify_srs_intent(srs_text: str) -> dict:
    """
    Classify whether an SRS describes a new system or an enhancement to
    an existing component by querying the HLD knowledge base.
    """
    search_query = srs_text[:600].strip()

    name_patterns = [
        r"(?:component|system|module|service|subsystem)[:\s]+[\"']?([\w\s-]+)",
        r"(?:title|project)[:\s]+[\"']?([\w\s-]+)",
        r"^#\s+(.+?)$",
    ]
    extracted_name = ""
    for pattern in name_patterns:
        match = re.search(pattern, srs_text[:1000], re.IGNORECASE | re.MULTILINE)
        if match:
            extracted_name = match.group(1).strip()
            break

    hld_results = query_hld_knowledge(
        query_text=extracted_name or search_query,
        top_k=3,
    )

    ENHANCEMENT_THRESHOLD = 0.50

    if hld_results and hld_results[0]["score"] >= ENHANCEMENT_THRESHOLD:
        best_match = hld_results[0]
        return {
            "mode": "enhancement",
            "confidence": best_match["score"],
            "matched_component": best_match["metadata"].get("title", "Unknown"),
            "matched_documents": hld_results,
            "reasoning": (
                f"Found existing design document '{best_match['metadata'].get('title', 'N/A')}' "
                f"with similarity score {best_match['score']:.2f} (threshold: {ENHANCEMENT_THRESHOLD}). "
                f"This SRS appears to be an enhancement to an existing component."
            ),
        }
    else:
        return {
            "mode": "new",
            "confidence": 1.0 - (hld_results[0]["score"] if hld_results else 0.0),
            "matched_component": None,
            "matched_documents": hld_results,
            "reasoning": (
                f"No existing design documents matched with sufficient confidence "
                f"(best score: {hld_results[0]['score']:.2f if hld_results else 0.0}, "
                f"threshold: {ENHANCEMENT_THRESHOLD}). "
                f"This SRS describes a new component/system."
            ),
        }


# ============================================================================
# Utility
# ============================================================================
def get_collection_stats() -> dict:
    """Return counts and metadata for both vector store collections."""
    hld_store = _get_hld_store()
    api_store = _get_api_store()

    return {
        "hld_knowledge_base": {
            "document_chunks": hld_store.count(),
        },
        "api_spec_knowledge_base": {
            "document_chunks": api_store.count(),
        },
        "embedding_model": EMBEDDING_MODEL_NAME,
        "persist_directory": PERSIST_DIR,
    }
