"""
HLD MCP Server — Main FastMCP Server
Exposes tools for SRS reading, RAG knowledge base querying,
HLD generation (new + enhancement), Collab sync, and publishing.

Follows the exact same architectural pattern as the existing
jira_server.py, build_server.py, and device_server.py.
"""

import os
import re
import glob
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

# Import FastMCP with fallback support across package versions
try:
    from mcp.server.fastmcp import FastMCP, Context
except ImportError:
    try:
        from fastmcp import FastMCP, Context
    except ImportError:
        raise ImportError(
            "Failed to import FastMCP. Please ensure 'mcp[cli]' or 'fastmcp' is installed via pip."
        )

from config import (
    TEMPLATES_DIR,
    SERVER_PORT,
    COLLAB_DEFAULT_SPACE_KEY,
    AUTO_SYNC_ENABLED,
    AUTO_SYNC_DAY_OF_WEEK,
    AUTO_SYNC_HOUR,
    AUTO_SYNC_MINUTE,
)

# Initialize FastMCP server
mcp = FastMCP("HLD Designer Agent")


# ============================================================================
# Helper: Get Collab URL and PAT from request headers, parameters, or env
# ============================================================================
def _get_collab_config(
    ctx: Context = None, pat_override: str = "", url_override: str = ""
) -> tuple[str, str]:
    """
    Extract Collab URL and PAT from parameters, incoming request headers, or env vars.
    Checks Starlette Request headers (case-insensitive) via ctx.request_context.request.
    """
    pat = pat_override.strip() if pat_override else ""
    url = url_override.strip() if url_override else ""

    if ctx and hasattr(ctx, "request_context") and ctx.request_context:
        # Check Starlette Request inside request_context (standard FastMCP SSE pattern)
        req = getattr(ctx.request_context, "request", None)
        if req and hasattr(req, "headers"):
            if not pat:
                pat = (
                    req.headers.get("x-collab-pat", "")
                    or req.headers.get("X-Collab-PAT", "")
                    or req.headers.get("x_collab_pat", "")
                    or req.headers.get("collab-pat", "")
                )
            if not url:
                url = (
                    req.headers.get("x-collab-url", "")
                    or req.headers.get("X-Collab-URL", "")
                    or req.headers.get("x_collab_url", "")
                    or req.headers.get("collab-url", "")
                )

        # Fallback check on request_context.headers
        if hasattr(ctx.request_context, "headers"):
            headers = ctx.request_context.headers
            if isinstance(headers, dict):
                if not pat:
                    pat = headers.get("x-collab-pat", "") or headers.get("X-Collab-PAT", "")
                if not url:
                    url = headers.get("x-collab-url", "") or headers.get("X-Collab-URL", "")
            elif hasattr(headers, "get"):
                if not pat:
                    pat = headers.get("x-collab-pat", "") or headers.get("X-Collab-PAT", "")
                if not url:
                    url = headers.get("x-collab-url", "") or headers.get("X-Collab-URL", "")

    if not pat:
        pat = os.environ.get("COLLAB_PAT", "")
    if not url:
        url = os.environ.get("COLLAB_BASE_URL", "")

    return url.strip(), pat.strip()


def _get_collab_pat(ctx: Context = None, pat_override: str = "") -> str:
    """Legacy helper for PAT only."""
    _, pat = _get_collab_config(ctx, pat_override=pat_override)
    return pat


# ============================================================================
# Tool 1: Read SRS File
# ============================================================================
@mcp.tool()
def read_srs_file(file_path: str, ctx: Context = None) -> str:
    """
    Read and parse a Software Requirements Specification (SRS) markdown file
    from the local workspace.

    :param file_path: Absolute or relative path to the SRS .md file.
                      Supports glob patterns like './requirements/*.md'.
    """
    try:
        # Handle glob patterns
        if "*" in file_path or "?" in file_path:
            matched_files = glob.glob(file_path, recursive=True)
            if not matched_files:
                return f"❌ No files matched the pattern: `{file_path}`"

            results = []
            for fp in sorted(matched_files):
                with open(fp, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                results.append(
                    f"---\n### 📄 File: `{os.path.basename(fp)}`\n"
                    f"**Path:** `{fp}`\n"
                    f"**Size:** {len(content)} chars\n\n{content}"
                )
            return (
                f"✅ Found **{len(matched_files)}** SRS file(s):\n\n"
                + "\n\n".join(results)
            )

        # Single file
        if not os.path.exists(file_path):
            # Check if only a filename was provided and search recursively
            filename = os.path.basename(file_path)
            matches = glob.glob(f"**/{filename}", recursive=True)
            if matches:
                file_path = matches[0]
            else:
                return (
                    f"❌ SRS file not found: `{file_path}`\n\n"
                    f"**Tip:** In VS Code, you can attach it directly using `#file:{filename}`."
                )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            return f"⚠️ SRS file `{file_path}` is empty."

        # Extract key sections for quick summary
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else os.path.basename(file_path)

        return (
            f"✅ **SRS Loaded Successfully**\n\n"
            f"- **Title:** {title}\n"
            f"- **File:** `{os.path.basename(file_path)}`\n"
            f"- **Size:** {len(content)} characters\n"
            f"- **Lines:** {content.count(chr(10)) + 1}\n\n"
            f"---\n\n{content}"
        )

    except PermissionError:
        return f"❌ Permission denied reading file: `{file_path}`"
    except Exception as e:
        return f"❌ Error reading SRS file: {str(e)}"


# ============================================================================
# Tool 2: Search Existing Designs (RAG Query)
# ============================================================================
@mcp.tool()
def search_existing_designs(
    query: str,
    search_type: str = "all",
    top_k: int = 5,
    ctx: Context = None,
) -> str:
    """
    Search the knowledge base for existing HLD documents and/or API specifications
    that are relevant to the given query. Uses vector similarity search (RAG).

    :param query: Natural language search query describing what you are looking for.
    :param search_type: 'hld' for design docs only, 'api' for API specs only, 'all' for both.
    :param top_k: Number of top results to return (default: 5).
    """
    try:
        from rag_engine import query_hld_knowledge, query_api_knowledge, search_all

        if search_type == "hld":
            results = query_hld_knowledge(query, top_k)
            label = "HLD Knowledge Base"
        elif search_type == "api":
            results = query_api_knowledge(query, top_k)
            label = "API Spec Knowledge Base"
        else:
            combined = search_all(query, top_k)
            # Format combined results
            output = f"🔍 **Knowledge Base Search Results** for: *\"{query}\"*\n\n"

            output += f"### 📐 HLD Documents ({len(combined['hld_results'])} matches)\n\n"
            if combined["hld_results"]:
                for i, r in enumerate(combined["hld_results"], 1):
                    source = r["metadata"].get("source", "Unknown")
                    title = r["metadata"].get("title", "Untitled")
                    output += (
                        f"**{i}.** [{title}] (Score: {r['score']})\n"
                        f"   Source: `{source}`\n"
                        f"   ```text\n{r['text']}\n   ```\n\n"
                    )
            else:
                output += "*No matching HLD documents found.*\n\n"

            output += f"### 🔌 API Specifications ({len(combined['api_results'])} matches)\n\n"
            if combined["api_results"]:
                for i, r in enumerate(combined["api_results"], 1):
                    source = r["metadata"].get("source", "Unknown")
                    title = r["metadata"].get("title", "Untitled")
                    output += (
                        f"**{i}.** [{title}] (Score: {r['score']})\n"
                        f"   Source: `{source}`\n"
                        f"   ```text\n{r['text']}\n   ```\n\n"
                    )
            else:
                output += "*No matching API specifications found.*\n\n"

            return output

        # Single-type results
        if not results:
            return f"⚠️ No results found in **{label}** for query: *\"{query}\"*"

        output = f"🔍 **{label} Results** ({len(results)} matches):\n\n"
        for i, r in enumerate(results, 1):
            source = r["metadata"].get("source", "Unknown")
            title = r["metadata"].get("title", "Untitled")
            output += (
                f"**{i}.** [{title}] (Score: {r['score']})\n"
                f"   Source: `{source}`\n"
                f"   ```text\n{r['text']}\n   ```\n\n"
            )
        return output

    except ImportError:
        return (
            "❌ RAG engine not available. The knowledge base has not been initialized yet.\n"
            "Use `sync_knowledge_base` to ingest documents first."
        )
    except Exception as e:
        return f"❌ Error searching knowledge base: {str(e)}"


# ============================================================================
# Tool 3: Generate HLD
# ============================================================================
@mcp.tool()
def generate_hld(
    srs_path: str = "",
    srs_content: str = "",
    component_name: str = "",
    force_mode: str = "auto",
    output_path: str = "",
    ctx: Context = None,
) -> str:
    """
    Generate a High-Level Design document from an SRS.
    You can provide a file path, just the filename (e.g. 'audio_subsystem_srs.md'),
    or pass the SRS content directly.
    Automatically detects whether to create a NEW design or an ENHANCEMENT update.

    :param srs_path: Path or filename of the SRS markdown file (e.g. 'audio_subsystem_srs.md').
    :param srs_content: Optional direct raw text of the SRS requirements.
    :param component_name: Optional component/system name. Auto-extracted from SRS if empty.
    :param force_mode: 'auto' (default), 'new' (force new HLD), or 'enhancement' (force delta).
    :param output_path: Optional output file path to save the generated HLD locally.
    """
    try:
        # Step 1: Resolve SRS content
        if not srs_content:
            if not srs_path:
                return "❌ Please provide an SRS file path, filename, or paste the SRS requirements."

            # If srs_path actually contains multiline requirements text
            if "\n" in srs_path or len(srs_path) > 300:
                srs_content = srs_path.strip()
            elif os.path.exists(srs_path):
                with open(srs_path, "r", encoding="utf-8") as f:
                    srs_content = f.read().strip()
            else:
                # Search recursively by filename across workspace
                filename = os.path.basename(srs_path)
                matches = glob.glob(f"**/{filename}", recursive=True)
                if matches:
                    with open(matches[0], "r", encoding="utf-8") as f:
                        srs_content = f.read().strip()
                    srs_path = matches[0]
                else:
                    return (
                        f"❌ SRS file `{srs_path}` not found.\n\n"
                        f"**Tip:** In VS Code, you can attach it directly using `#file:{filename}`."
                    )

        if not srs_content:
            return "⚠️ The provided SRS content is empty."

        # Extract component name if not provided
        if not component_name:
            title_match = re.search(r"^#\s+(.+)$", srs_content, re.MULTILINE)
            component_name = (
                title_match.group(1) if title_match else (os.path.basename(srs_path) if srs_path else "System")
            )

        # Step 2: Classify intent (new vs enhancement)
        mode = force_mode
        classification = None
        existing_context = ""

        if mode == "auto":
            try:
                from rag_engine import classify_srs_intent

                classification = classify_srs_intent(srs_content)
                mode = classification["mode"]
            except (ImportError, Exception):
                mode = "new"  # Default to new if RAG is unavailable

        # Step 3: Gather context from knowledge base
        try:
            from rag_engine import search_all

            context_results = search_all(
                query_text=f"{component_name} architecture design",
                top_k=5,
            )

            # Build context string from retrieved documents
            context_parts = []
            for r in context_results.get("hld_results", []):
                context_parts.append(
                    f"[Existing HLD - {r['metadata'].get('title', 'N/A')}]:\n{r['text']}"
                )
            for r in context_results.get("api_results", []):
                context_parts.append(
                    f"[API Spec - {r['metadata'].get('title', 'N/A')}]:\n{r['text']}"
                )
            existing_context = "\n\n---\n\n".join(context_parts)
        except (ImportError, Exception):
            existing_context = ""

        # Step 4: Load the appropriate template
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if mode == "enhancement":
            template_path = os.path.join(TEMPLATES_DIR, "delta_hld_template.md")
            version = "v1.1"
            prev_title = ""
            prev_url = ""

            if classification and classification.get("matched_documents"):
                best = classification["matched_documents"][0]
                prev_title = best["metadata"].get("title", "Previous Version")
                prev_url = best["metadata"].get("url", "")
                # Try to extract version from previous title
                v_match = re.search(r"v(\d+\.\d+)", prev_title)
                if v_match:
                    major, minor = v_match.group(1).split(".")
                    version = f"v{major}.{int(minor) + 1}"
        else:
            template_path = os.path.join(TEMPLATES_DIR, "new_hld_template.md")
            version = "v1.0"
            prev_title = ""
            prev_url = ""

        # Load template
        if os.path.exists(template_path):
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
        else:
            template = f"# High-Level Design — {component_name}\n\n*Template file not found. Generating freeform HLD.*"

        # Step 5: Fill template placeholders
        template = template.replace("{COMPONENT_NAME}", component_name)
        template = template.replace("{VERSION}", version)
        template = template.replace("{DATE}", now)
        template = template.replace("{SRS_FILE}", os.path.basename(srs_path))
        template = template.replace("{PREVIOUS_TITLE}", prev_title)
        template = template.replace("{PREVIOUS_URL}", prev_url)
        template = template.replace("{PREVIOUS_VERSION}", "v1.0")
        template = template.replace("{PREV_DATE}", "")
        template = template.replace("{PREV_AUTHOR}", "")
        template = template.replace("{CHANGE_SUMMARY}", component_name + " Enhancement")

        # Step 6: Assemble the full generation context for the Copilot LLM
        output = f"## 🏗️ HLD Generation Report\n\n"
        output += f"- **Mode:** {'🆕 New Design' if mode == 'new' else '🔄 Enhancement / Delta Update'}\n"
        output += f"- **Component:** {component_name}\n"
        output += f"- **Version:** {version}\n"
        output += f"- **SRS Source:** `{os.path.basename(srs_path)}`\n"

        if classification:
            output += f"- **Classification Confidence:** {classification['confidence']:.2f}\n"
            output += f"- **Reasoning:** {classification['reasoning']}\n"

        if mode == "enhancement" and prev_title:
            output += f"- **Supersedes:** {prev_title}\n"

        output += f"\n---\n\n"

        # Include the SRS content
        output += f"### 📋 SOURCE SRS REQUIREMENTS\n\n{srs_content}\n\n---\n\n"

        # Include retrieved context
        if existing_context:
            output += f"### 📚 RETRIEVED KNOWLEDGE BASE CONTEXT\n\n{existing_context}\n\n---\n\n"

        # Include the template
        output += f"### 📝 HLD TEMPLATE TO FOLLOW\n\n{template}\n\n---\n\n"

        # Instructions for the Copilot LLM
        output += (
            "### 🤖 GENERATION INSTRUCTIONS\n\n"
            "You are now an expert Software Architect. Using the SRS requirements above, "
            "the retrieved knowledge base context, and the HLD template structure, "
            "please generate a complete, professional High-Level Design document.\n\n"
            "**Rules:**\n"
            "1. Replace ALL `{LLM_GENERATE: ...}` placeholders with real, substantive content.\n"
            "2. Include proper, valid Mermaid diagrams (`graph TB` and `sequenceDiagram`).\n"
            "   - **CRITICAL MERMAID SYNTAX RULE:** In `sequenceDiagram`, NEVER put raw JSON payloads or curly braces `{}` directly on message arrow lines (e.g. `A->>B: msg {json}` causes parse errors!). Use clean method names like `A->>B: onDeviceAdded(deviceName, type)` or place payloads in a `Note over B: Payload: ...`.\n"
            "   - In `graph TB` diagrams, always quote labels with brackets/URIs: `Node[\"Audio Service (com.webos.service.audio)\"]`.\n"
            "3. Map every SRS requirement to a design decision.\n"
        )

        if mode == "enhancement":
            output += (
                "4. Clearly identify what changed vs. the existing baseline design.\n"
                "5. Assess backward compatibility for every modified interface.\n"
                "6. This is a DELTA update — do NOT rewrite unchanged sections from scratch.\n"
            )
        else:
            output += (
                "4. Design all sections from first principles based on the SRS.\n"
                "5. Propose a clean technology stack appropriate for the described system.\n"
            )

        # Save locally if output_path specified
        if output_path:
            try:
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(output)
                output += f"\n\n✅ HLD saved to: `{output_path}`"
            except Exception as e:
                output += f"\n\n⚠️ Could not save HLD to `{output_path}`: {e}"

        return output

    except Exception as e:
        return f"❌ Error generating HLD: {str(e)}"


# ============================================================================
# Tool 4: Sync Knowledge Base
# ============================================================================
@mcp.tool()
def sync_knowledge_base(
    hld_parent_page_id: str = "",
    api_parent_page_id: str = "",
    space_key: str = "",
    collab_pat: str = "",
    collab_url: str = "",
    force_full: bool = False,
    ctx: Context = None,
) -> str:
    """
    ADMINISTRATIVE ONLY: Ingest or re-index documentation from Collab into the local vector store.

    CRITICAL INSTRUCTION FOR AI AGENTS:
    - ONLY execute this tool when the user EXPLICITLY types words like "sync", "reindex", or "update knowledge base".
    - NEVER execute this tool to answer user questions, architectural lookups, searches, or design generation tasks!
    - If a search query returns few or specific results, synthesize the best answer from the search results or ask the user for clarification. DO NOT trigger this sync tool in response to a question.

    :param hld_parent_page_id: Root page ID containing your team's HLD documents (default: 598215130).
    :param api_parent_page_id: Root page ID containing your team's API documents (default: 1473985612).
    :param space_key: Confluence space key (default: WEBOSDOCS).
    :param collab_pat: Optional Personal Access Token override (otherwise read from headers/env).
    :param collab_url: Optional Collab Base URL override (e.g. 'https://collab.lge.com/main' or from headers/env).
    :param force_full: If True, re-indexes all pages. If False, only new/modified pages.
    """
    try:
        from collab_sync import get_incremental_updates
        from rag_engine import ingest_documents, get_collection_stats
        from config import COLLAB_HLD_PARENT_PAGE_ID, COLLAB_API_PARENT_PAGE_ID

        url, pat = _get_collab_config(ctx, pat_override=collab_pat, url_override=collab_url)
        space = space_key or COLLAB_DEFAULT_SPACE_KEY
        hld_parent = hld_parent_page_id or COLLAB_HLD_PARENT_PAGE_ID
        api_parent = api_parent_page_id or COLLAB_API_PARENT_PAGE_ID

        # Fetch updated pages strictly from your team's trees
        sync_result = get_incremental_updates(
            hld_parent_id=hld_parent,
            api_parent_id=api_parent,
            space_key=space,
            force_full=force_full,
            pat_override=pat,
            base_url_override=url,
        )

        hld_pages = sync_result.get("hld_pages", [])
        api_pages = sync_result.get("api_pages", [])
        hld_summary = sync_result.get("hld_summary", {})

        if not hld_pages and not api_pages:
            stats = get_collection_stats()
            return (
                f"✅ Knowledge base is already up-to-date for your team's trees!\n\n"
                f"**Configured Scope:**\n"
                f"- HLD Tree Root ID: `{hld_parent}`\n"
                f"- API Tree Root ID: `{api_parent}`\n\n"
                f"**Current Stats:**\n"
                f"- HLD Documents: {stats['hld_knowledge_base']['document_chunks']} chunks\n"
                f"- API Specs: {stats['api_spec_knowledge_base']['document_chunks']} chunks\n"
                f"- Embedding Model: `{stats['embedding_model']}`\n\n"
                f"Use `force_full=true` to re-index everything from scratch."
            )

        # Ingest HLD pages — with version_label in metadata
        hld_texts, hld_metas = [], []
        for page in hld_pages:
            hld_texts.append(page["body_text"])
            hld_metas.append({
                "source": f"collab:HLD:{page['page_id']}",
                "title": page["title"],
                "page_id": page["page_id"],
                "version": page["version"],
                "last_modified": page["last_modified"],
                "url": page.get("url", ""),
                "version_label": page.get("version_label", ""),
            })

        # Ingest API pages
        api_texts, api_metas = [], []
        for page in api_pages:
            api_texts.append(page["body_text"])
            api_metas.append({
                "source": f"collab:API:{page['page_id']}",
                "title": page["title"],
                "page_id": page["page_id"],
                "version": page["version"],
                "last_modified": page["last_modified"],
                "url": page.get("url", ""),
                "version_label": page.get("version_label", ""),
            })

        hld_count = ingest_documents(hld_texts, hld_metas, collection="hld", clear_first=True) if hld_texts else 0
        api_count = ingest_documents(api_texts, api_metas, collection="api", clear_first=True) if api_texts else 0

        stats = get_collection_stats()

        # Build version breakdown section
        versions_found = hld_summary.get("versions_found", [])
        hld_folders_indexed = hld_summary.get("hld_folders_indexed", [])
        lld_folders_skipped = hld_summary.get("lld_folders_skipped", [])

        version_lines = "\n".join(f"  - `{v}`" for v in versions_found) if versions_found else "  - (none)"
        hld_folder_lines = "\n".join(f"  - ✅ `{f}`" for f in hld_folders_indexed) if hld_folders_indexed else "  - (none)"
        lld_folder_lines = "\n".join(f"  - ⛔ `{f}`" for f in lld_folders_skipped) if lld_folders_skipped else "  - (none)"

        return (
            f"✅ **Knowledge Base Synced Successfully!**\n\n"
            f"**HLD Parent Tree (ID: `{hld_parent}`):** {len(hld_pages)} pages fetched → {hld_count} chunks indexed\n"
            f"**API Parent Tree (ID: `{api_parent}`):** {len(api_pages)} pages fetched → {api_count} chunks indexed\n"
            f"**Mode:** {'Full Re-index' if force_full else 'Incremental Update'}\n\n"
            f"---\n"
            f"**📂 webOS Versions Discovered:**\n{version_lines}\n\n"
            f"**✅ HLD Folders Indexed (Recursive):**\n{hld_folder_lines}\n\n"
            f"**⛔ LLD Folders Skipped:**\n{lld_folder_lines}\n\n"
            f"---\n"
            f"**Total Knowledge Base:**\n"
            f"- HLD Documents: {stats['hld_knowledge_base']['document_chunks']} total chunks\n"
            f"- API Specs: {stats['api_spec_knowledge_base']['document_chunks']} total chunks\n"
            f"- Embedding Model: `{stats['embedding_model']}`"
        )

    except ConnectionError as e:
        return f"❌ Could not connect to Collab API: {str(e)}"
    except ValueError as e:
        return f"❌ Configuration error: {str(e)}"
    except Exception as e:
        return f"❌ Error syncing knowledge base: {str(e)}"


# ============================================================================
# Tool 5: Publish HLD to Collab (Non-Destructive Versioned Page)
# ============================================================================
@mcp.tool()
def publish_hld_to_collab(
    title: str,
    content: str,
    space_key: str = "",
    parent_page_id: str = "",
    previous_page_id: str = "",
    collab_pat: str = "",
    collab_url: str = "",
    ctx: Context = None,
) -> str:
    """
    Publish a generated HLD document to Collab/Confluence as a BRAND-NEW page.
    CRITICAL: This tool NEVER overwrites or edits existing pages. It always creates
    a new versioned page and links back to the previous baseline if provided.

    :param title: Title for the new Collab page (e.g., '[v1.1] Audio Subsystem HLD').
    :param content: The full HLD markdown content to publish.
    :param space_key: Confluence space key (default: WEBOSDOCS).
    :param parent_page_id: Optional parent page ID to nest under.
    :param previous_page_id: Optional page ID of the previous baseline to link back to.
    :param collab_pat: Optional Personal Access Token override.
    :param collab_url: Optional Collab Base URL override (e.g. 'https://collab.lge.com/main' or from headers/env).
    """
    try:
        from collab_sync import publish_new_page, markdown_to_confluence_storage

        url, pat = _get_collab_config(ctx, pat_override=collab_pat, url_override=collab_url)
        space = space_key or COLLAB_DEFAULT_SPACE_KEY

        # Convert markdown to Confluence storage format
        content_html = markdown_to_confluence_storage(content)

        # Publish as a brand-new page (never overwrites)
        result = publish_new_page(
            title=title,
            space_key=space,
            content_html=content_html,
            parent_page_id=parent_page_id,
            previous_page_id=previous_page_id,
            pat_override=pat,
            base_url_override=url,
        )

        output = (
            f"✅ **HLD Published Successfully to Collab!**\n\n"
            f"- **Title:** {result['title']}\n"
            f"- **Page ID:** {result['page_id']}\n"
            f"- **Space:** `{space}`\n"
        )

        if result.get("url"):
            output += f"- **URL:** {result['url']}\n"

        if previous_page_id:
            output += (
                f"\n📌 **Non-Destructive:** Previous baseline page "
                f"(ID: {previous_page_id}) was NOT modified. "
                f"A supersedes banner was added to the new page.\n"
            )

        return output

    except ValueError as e:
        return f"❌ Configuration error: {str(e)}"
    except RuntimeError as e:
        return f"❌ Collab API error: {str(e)}"
    except Exception as e:
        return f"❌ Error publishing HLD: {str(e)}"


# ============================================================================
# Tool 6: Knowledge Base Stats
# ============================================================================
@mcp.tool()
def knowledge_base_status(ctx: Context = None) -> str:
    """
    Show the current status of the RAG knowledge base, including document counts,
    embedding model info, and last sync timestamps.
    """
    try:
        from rag_engine import get_collection_stats
        from collab_sync import _load_sync_metadata

        stats = get_collection_stats()
        sync_meta = _load_sync_metadata()

        output = (
            f"📊 **Knowledge Base Status**\n\n"
            f"### Vector Store Collections\n"
            f"| Collection | Document Chunks |\n"
            f"|---|---|\n"
            f"| HLD Knowledge Base | {stats['hld_knowledge_base']['document_chunks']} |\n"
            f"| API Spec Knowledge Base | {stats['api_spec_knowledge_base']['document_chunks']} |\n\n"
            f"### Configuration\n"
            f"- **Embedding Model:** `{stats['embedding_model']}`\n"
            f"- **Persist Directory:** `{stats['persist_directory']}`\n\n"
        )

        if sync_meta:
            output += "### Last Sync History\n"
            for space, info in sync_meta.items():
                output += (
                    f"- **{space}:** Last synced `{info.get('last_sync_time', 'Never')}` "
                    f"({info.get('pages_synced', 0)} pages)\n"
                )
        else:
            output += (
                "### Sync Status\n"
                "⚠️ No sync has been performed yet. "
                "Use `sync_knowledge_base` to ingest documents from Collab.\n"
            )

        return output

    except Exception as e:
        return f"❌ Error fetching knowledge base status: {str(e)}"


# ============================================================================
# MIDDLEWARE & APP SETUP
# ============================================================================
class HostHeaderBypassMiddleware:
    """ASGI Middleware to bypass Starlette/Uvicorn Host header validation."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") in ("http", "websocket"):
            headers = []
            for k, v in scope.get("headers", []):
                if k.lower() == b"host":
                    headers.append((b"host", b"localhost:8000"))
                else:
                    headers.append((k, v))
            scope["headers"] = headers
        await self.app(scope, receive, send)


# Build FastMCP Starlette app
app = mcp.sse_app()

# Health check route
async def health_check(request: Request) -> Response:
    """Health check endpoint for Kubernetes liveness/readiness probes."""
    return Response(content="OK", status_code=200)

app.routes.append(Route("/health", health_check, methods=["GET"]))


# ============================================================================
# Automated Weekly Sync — Background Worker
# ============================================================================
def _run_scheduled_weekly_sync() -> None:
    """
    Background worker executed by APScheduler on the configured cron schedule.
    Performs an incremental sync from Collab — fetches only pages modified
    since the last sync run. Logs all activity to stdout (visible via kubectl logs).
    Runs in a daemon thread so it never blocks active Copilot queries.
    """
    print(
        f"⏰ [Scheduler] Automated weekly sync started at "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        flush=True,
    )
    try:
        from collab_sync import get_incremental_updates
        from rag_engine import ingest_documents, get_collection_stats
        from config import (
            COLLAB_BASE_URL,
            COLLAB_PAT,
            COLLAB_HLD_PARENT_PAGE_ID,
            COLLAB_API_PARENT_PAGE_ID,
        )

        url = COLLAB_BASE_URL
        pat = COLLAB_PAT

        if not url or not pat:
            print(
                "⚠️ [Scheduler] COLLAB_BASE_URL or COLLAB_PAT is not configured. "
                "Skipping automated sync.",
                flush=True,
            )
            return

        print("📡 [Scheduler] Fetching incremental updates from Collab...", flush=True)
        updates = get_incremental_updates(
            hld_parent_page_id=COLLAB_HLD_PARENT_PAGE_ID,
            api_parent_page_id=COLLAB_API_PARENT_PAGE_ID,
            base_url=url,
            pat=pat,
            force_full=False,
        )

        hld_pages = updates.get("hld_pages", [])
        api_pages = updates.get("api_pages", [])
        total = len(hld_pages) + len(api_pages)

        if total == 0:
            print(
                "✅ [Scheduler] No new or modified pages found. Knowledge base is already up to date.",
                flush=True,
            )
            return

        print(
            f"📥 [Scheduler] Ingesting {len(hld_pages)} HLD pages and {len(api_pages)} API pages...",
            flush=True,
        )

        if hld_pages:
            ingest_documents(hld_pages, collection_type="hld")
        if api_pages:
            ingest_documents(api_pages, collection_type="api")

        stats = get_collection_stats()
        print(
            f"✅ [Scheduler] Weekly sync complete. "
            f"HLD chunks: {stats.get('hld_count', '?')}, "
            f"API chunks: {stats.get('api_count', '?')}",
            flush=True,
        )

    except Exception as e:
        print(f"❌ [Scheduler] Automated weekly sync failed: {e}", flush=True)


# ============================================================================
# Server Startup
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    from apscheduler.schedulers.background import BackgroundScheduler

    print(f"🏗️ HLD Designer Agent starting on port {SERVER_PORT} (SSE Transport)...")
    print(f"📡 SSE endpoint: http://0.0.0.0:{SERVER_PORT}/sse")
    from rag_engine import _get_hld_store, _get_api_store, EMBEDDING_MODEL_NAME
    print(f"🧠 Semantic Engine: {EMBEDDING_MODEL_NAME}")

    _get_hld_store()
    _get_api_store()
    print("✅ Local Semantic Engine ready! (100% Offline, Zero external downloads)")

    # Start the APScheduler background cron
    scheduler = BackgroundScheduler(daemon=True)
    if AUTO_SYNC_ENABLED:
        scheduler.add_job(
            func=_run_scheduled_weekly_sync,
            trigger="cron",
            day_of_week=AUTO_SYNC_DAY_OF_WEEK,
            hour=AUTO_SYNC_HOUR,
            minute=AUTO_SYNC_MINUTE,
            id="weekly_collab_sync",
            name="Weekly Collab Knowledge Base Sync",
            replace_existing=True,
            misfire_grace_time=3600,  # Allow up to 1 hour late if pod was down
        )
        scheduler.start()
        print(
            f"⏰ [Scheduler] Automated weekly sync scheduled: "
            f"every {AUTO_SYNC_DAY_OF_WEEK.upper()} at "
            f"{AUTO_SYNC_HOUR:02d}:{AUTO_SYNC_MINUTE:02d} UTC "
            f"(~{AUTO_SYNC_HOUR + 5:02d}:{AUTO_SYNC_MINUTE + 30:02d} IST)",
            flush=True,
        )
    else:
        print("⏸️ [Scheduler] AUTO_SYNC_ENABLED=false — automated weekly sync is disabled.", flush=True)

    # Wrap Starlette app with HostHeaderBypassMiddleware
    wrapped_app = HostHeaderBypassMiddleware(app)

    try:
        uvicorn.run(
            wrapped_app,
            host="0.0.0.0",
            port=SERVER_PORT,
            proxy_headers=True,
            forwarded_allow_ips="*",
        )
    finally:
        if AUTO_SYNC_ENABLED and scheduler.running:
            scheduler.shutdown(wait=False)
            print("🛑 [Scheduler] Background scheduler shut down cleanly.", flush=True)

