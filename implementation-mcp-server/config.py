"""
Code Implementation Agent — Configuration Module
Centralizes all environment-driven settings for workspace paths,
vector store, template directories, and server configuration.
"""

import os

# ============================================================================
# Workspace Mount (Wall Repo / Source Code)
# ============================================================================
WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/app/workspace")

# ============================================================================
# Golden Templates Directory
# ============================================================================
TEMPLATES_DIR = os.environ.get("TEMPLATES_DIR", "/app/templates")

# ============================================================================
# Vector Store Persistence (ChromaDB on-disk)
# ============================================================================
PERSIST_DIR = os.environ.get("PERSIST_DIR", "/app/vector_store")

STANDARDS_COLLECTION_NAME = "coding_standards"
API_COLLECTION_NAME = "api_registry"

# ============================================================================
# Tree-sitter Language Support
# ============================================================================
SUPPORTED_LANGUAGES = ["c", "cpp", "java", "dart"]

# ============================================================================
# Server
# ============================================================================
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8000"))
