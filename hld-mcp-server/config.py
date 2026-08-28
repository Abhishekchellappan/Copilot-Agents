"""
HLD MCP Server — Configuration Module
Centralizes all environment-driven settings for embeddings, LLM, Collab API,
and local storage paths.
"""

import os

# ============================================================================
# Collab / Confluence REST API
# ============================================================================
COLLAB_BASE_URL = os.environ.get(
    "COLLAB_BASE_URL", "http://collab.lge.com/main/rest/api/content"
).rstrip("/")

COLLAB_PAT = os.environ.get("COLLAB_PAT", "")

COLLAB_HLD_SPACE_KEY = os.environ.get("COLLAB_HLD_SPACE_KEY", "TVARCHDOCS")
COLLAB_API_SPACE_KEY = os.environ.get("COLLAB_API_SPACE_KEY", "WEBOSDOCS")
COLLAB_DEFAULT_SPACE_KEY = os.environ.get("COLLAB_DEFAULT_SPACE_KEY", "TVARCHDOCS")

# Team-specific documentation parent tree IDs
COLLAB_HLD_PARENT_PAGE_ID = os.environ.get("COLLAB_HLD_PARENT_PAGE_ID", "598215130")
COLLAB_API_PARENT_PAGE_ID = os.environ.get("COLLAB_API_PARENT_PAGE_ID", "1473985612")

# ============================================================================
# HLD Selective Filtering Keywords
# Pages/folders whose titles contain any INCLUDE keyword will be recursively indexed.
# Pages/folders whose titles contain any EXCLUDE keyword will be completely skipped.
# These apply to the HLD tree traversal only (not the API tree).
# ============================================================================
HLD_INCLUDE_KEYWORDS = ["HLD", "High Level Design", "High-Level Design", "Architecture"]
HLD_EXCLUDE_KEYWORDS = ["LLD", "Low Level Design", "Low-Level Design"]

# ============================================================================
# Embedding Model (Local HuggingFace — runs inside the container, zero cost)
# ============================================================================
EMBEDDING_MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5"
)

# ============================================================================
# Vector Store Persistence (ChromaDB on-disk)
# ============================================================================
PERSIST_DIR = os.environ.get("PERSIST_DIR", "/app/vector_store")

# Collection names inside ChromaDB
HLD_COLLECTION_NAME = "hld_knowledge_base"
API_COLLECTION_NAME = "api_spec_knowledge_base"

# ============================================================================
# Local Paths (inside the container or workspace)
# ============================================================================
TEMPLATES_DIR = os.environ.get("TEMPLATES_DIR", "/app/templates")

# ============================================================================
# Sync Metadata Tracking
# ============================================================================
SYNC_METADATA_PATH = os.environ.get(
    "SYNC_METADATA_PATH", "/app/vector_store/sync_metadata.json"
)

# ============================================================================
# Server
# ============================================================================
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8000"))

# ============================================================================
# Automated Background Sync Schedule (APScheduler)
# Runs an incremental Collab sync on a cron schedule inside the container.
# ============================================================================
AUTO_SYNC_ENABLED = os.environ.get("AUTO_SYNC_ENABLED", "true").lower() in ("1", "true", "yes")
AUTO_SYNC_DAY_OF_WEEK = os.environ.get("AUTO_SYNC_DAY_OF_WEEK", "mon")  # Monday
AUTO_SYNC_HOUR = int(os.environ.get("AUTO_SYNC_HOUR", "2"))             # 02:00 UTC (07:30 IST)
AUTO_SYNC_MINUTE = int(os.environ.get("AUTO_SYNC_MINUTE", "0"))
