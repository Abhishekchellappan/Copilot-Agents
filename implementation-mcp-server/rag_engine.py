import uuid
import chromadb
from chromadb.utils import embedding_functions

# Import config constants
from config import PERSIST_DIR, STANDARDS_COLLECTION_NAME, API_COLLECTION_NAME

# Global variables for lazy initialization
_chroma_client = None
_embedding_function = None
_standards_collection = None
_api_collection = None

def _log(message: str):
    """Simple logging helper."""
    print(f"[rag_engine] {message}", flush=True)

def _init_chroma():
    """Initializes the ChromaDB client and embedding function lazily."""
    global _chroma_client, _embedding_function
    if _chroma_client is None:
        _log(f"Initializing ChromaDB client at {PERSIST_DIR}")
        _chroma_client = chromadb.PersistentClient(path=PERSIST_DIR)
        
        _log("Initializing sentence-transformers embedding function (all-MiniLM-L6-v2)")
        _embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

def get_standards_collection():
    """
    Returns the coding standards ChromaDB collection.
    Initializes the client and collection lazily if necessary.
    """
    global _standards_collection
    _init_chroma()
    if _standards_collection is None:
        _standards_collection = _chroma_client.get_or_create_collection(
            name=STANDARDS_COLLECTION_NAME,
            embedding_function=_embedding_function
        )
    return _standards_collection

def get_api_collection():
    """
    Returns the API registry ChromaDB collection.
    Initializes the client and collection lazily if necessary.
    """
    global _api_collection
    _init_chroma()
    if _api_collection is None:
        _api_collection = _chroma_client.get_or_create_collection(
            name=API_COLLECTION_NAME,
            embedding_function=_embedding_function
        )
    return _api_collection

def search_standards(query: str, top_k: int = 5) -> list[dict]:
    """
    Searches the coding standards collection for the given query.
    
    Args:
        query: The search string.
        top_k: Number of results to return.
        
    Returns:
        List of dictionaries with 'text', 'metadata', and 'distance' keys.
    """
    collection = get_standards_collection()
    if collection.count() == 0:
        _log("Standards collection is empty. Returning empty results.")
        return []
        
    _log(f"Searching standards for: '{query}' (top_k={top_k})")
    results = collection.query(
        query_texts=[query],
        n_results=top_k
    )
    
    return _format_results(results)

def search_api_registry(query: str, language_filter: str = '', top_k: int = 5) -> list[dict]:
    """
    Searches the API documentation collection, optionally filtering by language.
    
    Args:
        query: The search string.
        language_filter: Optional language to filter by (matches 'language' metadata).
        top_k: Number of results to return.
        
    Returns:
        List of dictionaries with 'text', 'metadata', and 'distance' keys.
    """
    collection = get_api_collection()
    if collection.count() == 0:
        _log("API registry collection is empty. Returning empty results.")
        return []
        
    _log(f"Searching API registry for: '{query}' (language='{language_filter}', top_k={top_k})")
    
    where_clause = None
    if language_filter:
        where_clause = {"language": language_filter}
        
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where_clause
    )
    
    return _format_results(results)

def _format_results(results: dict) -> list[dict]:
    """Helper to format ChromaDB query results into a list of dicts."""
    formatted = []
    if not results or not results.get("documents") or not results["documents"][0]:
        return formatted
        
    for i in range(len(results["documents"][0])):
        doc = {
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
            "distance": results["distances"][0][i] if results.get("distances") else 0.0
        }
        formatted.append(doc)
    return formatted

def ingest_standards(documents: list[dict]):
    """
    Ingests coding standard documents into the collection.
    
    Args:
        documents: List of dicts, each with 'text' and 'metadata' keys.
    """
    if not documents:
        return
        
    collection = get_standards_collection()
    _log(f"Ingesting {len(documents)} standard documents.")
    _ingest_to_collection(collection, documents)

def ingest_api_docs(documents: list[dict]):
    """
    Ingests API documentation into the collection.
    
    Args:
        documents: List of dicts, each with 'text' and 'metadata' keys.
    """
    if not documents:
        return
        
    collection = get_api_collection()
    _log(f"Ingesting {len(documents)} API documents.")
    _ingest_to_collection(collection, documents)

def _ingest_to_collection(collection, documents: list[dict]):
    """Helper to add documents to a ChromaDB collection."""
    texts = []
    metadatas = []
    ids = []
    
    for doc in documents:
        texts.append(doc.get("text", ""))
        metadatas.append(doc.get("metadata", {}))
        # Generate a unique ID if one isn't provided
        ids.append(doc.get("id", str(uuid.uuid4())))
        
    collection.add(
        documents=texts,
        metadatas=metadatas,
        ids=ids
    )
    _log(f"Successfully ingested {len(documents)} documents.")

def get_collection_stats() -> dict:
    """
    Returns document counts for both collections.
    
    Returns:
        Dict with 'coding_standards_count' and 'api_registry_count'.
    """
    _init_chroma()
    
    stats = {
        "coding_standards_count": 0,
        "api_registry_count": 0
    }
    
    try:
        # Check if collections exist before getting them to avoid creating them just to count
        collections = _chroma_client.list_collections()
        collection_names = [c.name for c in collections]
        
        if STANDARDS_COLLECTION_NAME in collection_names:
            stats["coding_standards_count"] = get_standards_collection().count()
             
        if API_COLLECTION_NAME in collection_names:
            stats["api_registry_count"] = get_api_collection().count()
    except Exception as e:
        _log(f"Error getting collection stats: {e}")
        
    return stats
