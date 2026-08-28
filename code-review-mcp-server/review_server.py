import os
import re
import json
import base64
import urllib3
import requests
from starlette.requests import Request
from starlette.responses import Response

# Disable SSL warnings for corporate internal servers (wall.lge.com)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Import FastMCP — matching the exact import pattern proven to work in Jira & Build servers
try:
    from mcp.server.fastmcp import FastMCP, Context
except ImportError:
    try:
        from fastmcp import FastMCP, Context
    except ImportError:
        raise ImportError("Failed to import FastMCP. Please ensure 'mcp[cli]' or 'fastmcp' is installed via pip.")

# Initialize FastMCP server
mcp = FastMCP("Code Review Agent")

# ============================================================================
# CONFIGURATION
# ============================================================================
GERRIT_URL = os.environ.get("GERRIT_URL", "https://wall.lge.com").rstrip("/")
GERRIT_USER = os.environ.get("GERRIT_USER", "")
GERRIT_HTTP_PASSWORD = os.environ.get("GERRIT_HTTP_PASSWORD", "")

# AI Agent signature appended to every Gerrit comment
AI_SIGNATURE = "\n\n---\n*Posted by LGSI Gpos AI Agent*"
# ============================================================================
# BULLETPROOF GERRIT REST API ENGINE
# ============================================================================

def _gerrit_auth_header(ctx: Context = None, request: Request = None) -> dict:
    """
    Build HTTP Basic Auth header for Gerrit REST API.
    Extracts X-Gerrit-User and X-Gerrit-Pass from mcp.json headers,
    falling back to server environment variables.
    """
    user = ""
    password = ""

    # Extract headers from incoming MCP request
    req = None
    if request:
        req = request
    elif ctx and hasattr(ctx, "request_context") and ctx.request_context:
        req = getattr(ctx.request_context, "request", None)

    if req:
        # Check all casing variations for mcp.json headers
        for k, v in req.headers.items():
            k_lower = k.lower()
            if k_lower == "x-gerrit-user":
                user = v
            elif k_lower == "x-gerrit-pass":
                password = v

        if user:
            print(f"🔑 Auth Info: Extracted user '{user}' from mcp.json request headers")

    # Fallback to server env vars
    if not user:
        user = GERRIT_USER
    if not password:
        password = GERRIT_HTTP_PASSWORD

    if user and password:
        credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json"
        }

    print("⚠️ Auth Warning: No Gerrit user credentials provided in mcp.json headers or env vars")
    return {"Content-Type": "application/json"}


def _parse_gerrit_json(text: str):
    """
    Safely strip Gerrit's magic security prefix )]}' and parse JSON.
    """
    cleaned = text.strip()
    if cleaned.startswith(")]}'"):
        cleaned = cleaned[4:].strip()
    return json.loads(cleaned)


def _gerrit_get(endpoint: str, ctx: Context = None, request: Request = None) -> dict:
    """
    Bulletproof GET request to Gerrit REST API.
    Tries authenticated /a/ endpoint first, with automatic fallback to unauthenticated /.
    """
    headers = _gerrit_auth_header(ctx=ctx, request=request)
    endpoint_clean = endpoint.lstrip("/")

    # Try URLs in order: /a/endpoint -> /endpoint
    urls_to_try = []
    if "Authorization" in headers:
        urls_to_try.append(f"{GERRIT_URL}/a/{endpoint_clean}")
    urls_to_try.append(f"{GERRIT_URL}/{endpoint_clean}")

    last_error = None
    for url in urls_to_try:
        try:
            print(f"🌐 Gerrit GET Request: {url}")
            response = requests.get(url, headers=headers, timeout=30, verify=False)
            print(f"📡 Gerrit Response Status: {response.status_code}")

            if response.status_code == 200:
                return _parse_gerrit_json(response.text)

            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as e:
            last_error = str(e)

    auth_state = "with credentials" if "Authorization" in headers else "UNAUTHENTICATED (missing X-Gerrit-User / X-Gerrit-Pass in mcp.json)"
    raise Exception(f"Gerrit API GET failed ({auth_state}). Endpoint: {endpoint_clean}. Error: {last_error}")


def _gerrit_post(endpoint: str, payload: dict, ctx: Context = None, request: Request = None) -> dict:
    """
    Bulletproof POST request to Gerrit REST API.
    """
    headers = _gerrit_auth_header(ctx=ctx, request=request)
    endpoint_clean = endpoint.lstrip("/")

    urls_to_try = []
    if "Authorization" in headers:
        urls_to_try.append(f"{GERRIT_URL}/a/{endpoint_clean}")
    urls_to_try.append(f"{GERRIT_URL}/{endpoint_clean}")

    last_error = None
    for url in urls_to_try:
        try:
            print(f"🌐 Gerrit POST Request: {url}")
            response = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            print(f"📡 Gerrit Response Status: {response.status_code}")

            if response.status_code in (200, 204):
                if response.status_code == 204 or not response.text.strip():
                    return {"status": "ok"}
                return _parse_gerrit_json(response.text)

            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as e:
            last_error = str(e)

    auth_state = "with credentials" if "Authorization" in headers else "UNAUTHENTICATED (missing X-Gerrit-User / X-Gerrit-Pass in mcp.json)"
    raise Exception(f"Gerrit API POST failed ({auth_state}). Endpoint: {endpoint_clean}. Error: {last_error}")


def _extract_change_id(permalink_or_id: str) -> str:
    """
    Extract change ID number or project-qualified change ID from ANY input format:
    - '770233'
    - 'https://wall.lge.com/c/770233'
    - 'https://wall.lge.com/c/module/starfish-camera-pipeline/+/770233'
    - 'https://wall.lge.com/#/c/770233/'
    - 'module/starfish-camera-pipeline/+/770233'
    """
    input_str = permalink_or_id.strip().rstrip("/")

    # Pattern 1: Match numeric ID after /+/ or /c/ (e.g. /+/770233 -> 770233)
    match_url = re.search(r"/(?:\+/|c/)?(\d{4,8})", input_str)
    if match_url:
        return match_url.group(1)

    # Pattern 2: Match any standalone 4-8 digit number
    match_num = re.search(r"\b(\d{4,8})\b", input_str)
    if match_num:
        return match_num.group(1)

    return input_str


# ========================================================# ============================================================================
# MASTER C++ & API CODE REVIEW RULES ENGINE
# ============================================================================

DEFAULT_REVIEW_RULES = [
    {
        "id": "COPYRIGHT_YEAR",
        "category": "Legal / Copyright",
        "pattern": r"Copyright\s+\(c\)\s+\d{4}[-–]\d{4}",
        "check": "Verify copyright year range includes the current year (2026).",
        "severity": "Warning"
    },
    {
        "id": "HARDCODED_IP",
        "category": "Security",
        "pattern": r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b",
        "check": "Hardcoded IP address detected. Use configuration files or environment variables.",
        "severity": "Error"
    },
    {
        "id": "HARDCODED_PASSWORD",
        "category": "Security",
        "pattern": r"(?i)(password|passwd|secret|api_key|token)\s*=\s*[\"'][^\"']+[\"']",
        "check": "Potential hardcoded credentials detected. Use secure vault or environment variables.",
        "severity": "Critical"
    },
    {
        "id": "RAW_DELETE",
        "category": "C++ Core Guidelines [R.3/R.11]",
        "pattern": r"\bdelete\s+[\w_]+",
        "check": "Raw delete found. Use std::unique_ptr or std::shared_ptr for resource management.",
        "severity": "Error"
    },
    {
        "id": "C_STYLE_CAST",
        "category": "C++ Core Guidelines [ES.48]",
        "pattern": r"\(\s*(?:int|char|float|double|long|void\s*\*)\s*\)\s*[\w_]+",
        "check": "C-style cast detected. Use C++ named casts (static_cast, const_cast, reinterpret_cast).",
        "severity": "Error"
    },
    {
        "id": "TODO_FIXME",
        "category": "Code Quality",
        "pattern": r"(?i)(TODO|FIXME|HACK|WORKAROUND)",
        "check": "Unresolved TODO/FIXME comment found. Address or create a follow-up ticket.",
        "severity": "Info"
    },
    {
        "id": "PRINTF_DEBUG",
        "category": "Code Quality",
        # Added \b to prevent matching things like g_strdup_printf
        "pattern": r"\b(?i)(printf\s*\(|std::cout|console\.log|System\.out\.print)",
        "check": "Debug print statement found. Use proper logging framework instead.",
        "severity": "Warning"
    },
    {
        "id": "EMPTY_CATCH",
        "category": "Error Handling",
        "pattern": r"catch\s*\([^)]*\)\s*\{\s*\}",
        "check": "Empty catch block found. Silently swallowing exceptions hides bugs.",
        "severity": "Error"
    },
]


def _apply_rules_to_code(code_text: str, filename: str = "") -> list:
    """
    Apply all review rules against source code.
    Returns a list of finding dicts.
    """
    findings = []
    lines = code_text.split("\n")

    for line_num, line_content in enumerate(lines, 1):
        for rule in DEFAULT_REVIEW_RULES:
            if rule["pattern"] and re.search(rule["pattern"], line_content):
                findings.append({
                    "line": line_num,
                    "file": filename,
                    "content": line_content.strip(),
                    # Removed the **[Warning]** prefix here!
                    "message": f"[{rule['category']}] {rule['check']}",
                    "severity": rule["severity"],
                    "category": rule["category"],
                    "rule_id": rule["id"]
                })

    return findings


# ============================================================================
# MCP TOOLS
# ============================================================================

@mcp.tool()
def review_local_code(code_text: str, filename: str = "workspace_file", ctx: Context = None) -> str:
    """
    Review local workspace code or pasted code against ISO C++, Google Style, and HS API rules.
    Outputs line-by-line review comments directly to the VS Code Chat Window.

    :param code_text: The source code text to review.
    :param filename: The filename for context (e.g., 'CMakeLists.txt', 'main.cpp').
    """
    try:
        findings = _apply_rules_to_code(code_text, filename)

        if not findings:
            return f"✅ **Code Review PASSED** for `{filename}`!\nNo issues found against current review rules."

        output = (
            f"🔍 **Code Review Report** for `{filename}` ({len(findings)} issue(s) found):\n\n"
            f"| # | Line | Severity | Category | Issue |\n"
            f"| :--- | :--- | :--- | :--- | :--- |\n"
        )

        for i, f in enumerate(findings, 1):
            output += f"| {i} | L{f['line']} | {f['severity']} | {f['category']} | {f['message']} |\n"

        output += "\n---\n\n**Detailed Findings:**\n\n"
        for i, f in enumerate(findings, 1):
            output += (
                f"**#{i}** — Line {f['line']}:\n"
                f"```\n{f['content']}\n```\n"
                f"{f['message']}\n\n"
            )

        return output
    except Exception as e:
        return f"Error executing review_local_code: {str(e)}"


@mcp.tool()
def analyze_gerrit_change(
    url: str = "",
    change_id: str = "",
    target: str = "",
    change_id_or_url: str = "",
    ctx: Context = None
) -> str:
    """
    Fetch modified code diffs, changed files, and comment threads for a Gerrit change from wall.lge.com.
    Use this tool whenever the user asks to review a Gerrit change, Gerrit permalink, URL, or Change ID.
    This tool extracts the modified code lines so that Copilot can analyze them against CODE_REVIEW_RULES.md.

    :param url: Full Gerrit URL (e.g. 'https://wall.lge.com/c/module/starfish-camera-pipeline/+/770233')
    :param change_id: Gerrit Change ID number (e.g. '770233')
    :param target: Any Gerrit URL or change ID provided by the user
    """
    try:
        raw_input = url or change_id or target or change_id_or_url
        if not raw_input:
            return "❌ Please provide a Gerrit Change URL or Change ID number."

        change_num = _extract_change_id(raw_input)
        print(f"🔍 Analyzing Gerrit Change: extracted ID '{change_num}' from input '{raw_input}'")

        # Step 1: Fetch change detail with revision metadata
        change_detail = {}
        try:
            change_detail = _gerrit_get(f"changes/{change_num}/detail?o=CURRENT_REVISION&o=CURRENT_COMMIT", ctx=ctx)
        except Exception:
            try:
                change_detail = _gerrit_get(f"changes/{change_num}/detail", ctx=ctx)
            except Exception as e:
                return (
                    f"❌ **Failed to fetch Gerrit Change {change_num}** from {GERRIT_URL}.\n\n"
                    f"**Details**: {str(e)}\n\n"
                    f"💡 **Troubleshooting Checklist**:\n"
                    f"1. Make sure your VS Code `mcp.json` has `X-Gerrit-User` and `X-Gerrit-Pass` headers configured.\n"
                    f"2. Generate an HTTP Password at `https://wall.lge.com` ➔ Settings ➔ HTTP Password.\n"
                    f"3. Verify change {change_num} exists and you have access permissions."
                )

        subject = change_detail.get("subject", "Gerrit Change " + change_num)
        project = change_detail.get("project", "Unknown Project")
        owner = change_detail.get("owner", {}).get("name", "Developer")
        current_revision = change_detail.get("current_revision", "current") or "current"

        # Step 2: Fetch list of changed files in current revision
        try:
            files = _gerrit_get(f"changes/{change_num}/revisions/{current_revision}/files", ctx=ctx)
        except Exception:
            # Fallback to 'current' revision alias
            files = _gerrit_get(f"changes/{change_num}/revisions/current/files", ctx=ctx)

        # Remove /COMMIT_MSG
        files.pop("/COMMIT_MSG", None)

        if not files:
            return f"✅ No modified code files found in Gerrit change **{change_num}** ({subject})."

        # Step 2.5: Fetch existing comment threads to track resolution status
        try:
            comments_data = _gerrit_get(f"changes/{change_num}/comments", ctx=ctx)
        except Exception:
            comments_data = {}

        total_unresolved = 0
        total_resolved = 0
        for filepath, comments in comments_data.items():
            for comment in comments:
                if comment.get("unresolved", False):
                    total_unresolved += 1
                else:
                    total_resolved += 1

        # Step 3: Fetch diff for each file and build line-numbered diff report for Copilot
        diff_output = ""
        total_files = len(files)

        for filepath in files.keys():
            try:
                diff_endpoint = f"changes/{change_num}/revisions/{current_revision}/files/{requests.utils.quote(filepath, safe='')}/diff"
                diff_data = _gerrit_get(diff_endpoint, ctx=ctx)

                file_diff_lines = []
                current_line = 1

                for content_block in diff_data.get("content", []):
                    if "skip" in content_block:
                        current_line += content_block["skip"]
                    if "ab" in content_block:
                        current_line += len(content_block["ab"])
                    if "b" in content_block:
                        for line in content_block["b"]:
                            file_diff_lines.append(f"L{current_line}: {line}")
                            current_line += 1

                if file_diff_lines:
                    diff_output += f"### 📄 `{filepath}`\n```cpp\n"
                    diff_output += "\n".join(file_diff_lines)
                    diff_output += "\n```\n\n"

            except Exception:
                continue

        if not diff_output:
            return f"✅ No modified code text found in Gerrit change **{change_num}** ({subject})."

        # Step 4: Return line-numbered diffs with instructions for Copilot to perform the review
        prompt = (
            f"🔍 **Gerrit Code Review Data** for Change **{change_num}**:\n"
            f"- **Subject**: {subject}\n"
            f"- **Project**: {project}\n"
            f"- **Owner**: {owner}\n"
            f"- **Files Changed**: {total_files}\n"
            f"- **Existing Gerrit Threads**: {total_unresolved} Unresolved, {total_resolved} Resolved\n\n"
            f"--- MODIFIED CODE LINES WITH LINE NUMBERS (SIDE B) ---\n\n"
            f"{diff_output}\n"
            f"---\n\n"
            f"⚠️ **ATTENTION COPILOT (YOU ARE THE CODE REVIEWER):**\n"
            f"The code above contains the exact modified lines fetched from Gerrit with line numbers.\n"
            f"YOU MUST NOW PERFORM THE CODE REVIEW YOURSELF by following these steps:\n\n"
            f"1. Read the `CODE_REVIEW_RULES.md` file in the workspace root.\n"
            f"2. Evaluate every line in the code diffs above against ALL rules in `CODE_REVIEW_RULES.md` (ISO C++, Google Style, Smart Pointers, Const correctness, HS API Rules, Security, webOS Platform rules).\n"
            f"3. **DO NOT SEARCH LOCAL DISK**: Perform your review EXCLUSIVELY on the diff text provided above. Do NOT search local workspace folders or files for this Gerrit change.\n"
            f"4. **DEFECT-ONLY RULE**: ONLY generate review comments for **actual issues, bugs, security flaws, performance concerns, or rule violations**. STRICTLY DO NOT generate comments praising or complimenting code lines that are correct.\n"
            f"4. Generate a comprehensive Code Review Report in chat containing:\n"
            f"   - **New Code Issues**: List every issue found with exact file path, line number (e.g. L45), rule category, and description.\n"
            f"   - **Open Discussions**: Mention the {total_unresolved} Unresolved Comments on Gerrit.\n"
            f"   - **Voting Recommendation**: Explicitly recommend `Code-Review -1` (Errors/Security), `Code-Review 0` (Warnings), or `Code-Review +1` (Clean Pass & All Threads Resolved).\n"
            f"5. Ask the user:\n"
            f"   'Where would you like to post these review comments?\n"
            f"   1️⃣ 🌐 Post directly to Gerrit\n"
            f"   2️⃣ 💬 Keep in VS Code Chat Window'\n\n"
            f"6. IMPORTANT: If the user selects 1, YOU MUST invoke `post_gerrit_review_comments` and pass your findings using the `review_comments` JSON dictionary argument (e.g. `{{\"src/main.cpp\": [{{\"line\": 45, \"message\": \"Fix this\"}}]}}`).\n"
            f"7. DO NOT ask the user to set up SSH keys or Git credentials — authentication is ALREADY handled automatically by the MCP server using HTTP Basic Auth via headers in `mcp.json`!\n"
            f"8. DO NOT include severity or category prefixes like `⚠️ **Code Quality**:` or `**Maintainability**:` in the JSON `message` strings. Output plain issue description text only."
        )

        return prompt
    except Exception as e:
        return f"Error executing analyze_gerrit_change: {str(e)}"


@mcp.tool()
def post_gerrit_review_comments(
    review_comments: dict = None,
    llm_review_text: str = "",
    url: str = "",
    change_id: str = "",
    target: str = "",
    change_id_or_url: str = "",
    revision_id: str = "current",
    ctx: Context = None
) -> str:
    """
    Post inline unresolved review comments to a Gerrit change.
    Each comment includes the AI agent signature footer.
    This tool should ONLY be called after the user explicitly confirms posting to Gerrit.
    
    :param review_comments: A structured dictionary mapping file paths to lists of comments.
                            Example: {"src/main.cpp": [{"line": 45, "message": "Issue details"}]}
    """
    try:
        raw_input = url or change_id or target or change_id_or_url
        if not raw_input:
            return "❌ Missing Gerrit change URL or ID to post."

        change_num = _extract_change_id(raw_input)

        if not review_comments or not isinstance(review_comments, dict):
            return (
                "❌ Missing or invalid `review_comments` dictionary. "
                "Copilot must provide structured JSON findings. "
                "Example: `{\"src/main.cpp\": [{\"line\": 45, \"message\": \"Fix this\"}]}`"
            )

        # Build Gerrit review payload with inline comments
        gerrit_comments = {}
        total_comments = 0

        for filepath, comments in review_comments.items():
            file_comments = []
            for comment in comments:
                raw_msg = comment.get("message", "").strip()
                
                # 1. Strip out any legacy duplicate signatures
                clean_msg = re.sub(r"_Comment provided by LGSI_Gpos_AI_agent_", "", raw_msg, flags=re.IGNORECASE)
                clean_msg = re.sub(r"---\s*\*Posted by LGSI Gpos AI Agent\*", "", clean_msg, flags=re.IGNORECASE)
                
                # 2. Strip out category/severity prefixes (e.g. ⚠️ **Code Quality**:, **Maintainability**:)
                clean_msg = re.sub(r"^(?:[⚠️⚡🚨💡ℹ️]\s*)?(?:\*\*)?(?:Code Quality|Maintainability|Security|Code Style|Warning|Error|Critical|Info|C\+\+ Core Guidelines|Google C\+\+ Style)(?:\*\*)?:\s*", "", clean_msg.strip(), flags=re.IGNORECASE)
                
                final_msg = clean_msg.strip() + AI_SIGNATURE
                
                file_comments.append({
                    "line": comment.get("line", 0),
                    "message": final_msg,
                    "unresolved": True
                })
                total_comments += 1
            gerrit_comments[filepath] = file_comments

        payload = {
            "tag": "autogenerated:ai-reviewer",
            "message": "AI Code Review completed by LGSI_Gpos_AI_agent.",
            "labels": {
                "Code-Review": 0
            },
            "comments": gerrit_comments
        }

        # Post to Gerrit
        _gerrit_post(f"changes/{change_num}/revisions/{revision_id}/review", payload, ctx=ctx)

        return (
            f"✅ **Successfully posted {total_comments} review comment(s) to Gerrit!**\n\n"
            f"- **Change**: {change_num}\n"
            f"- **Comments**: {total_comments} inline unresolved comment(s)\n"
            f"🔗 View in Gerrit: {GERRIT_URL}/c/{change_num}"
        )
    except Exception as e:
        return f"Error executing post_gerrit_review_comments: {str(e)}"

@mcp.tool()
def get_gerrit_comments(
    url: str = "",
    change_id: str = "",
    target: str = "",
    change_id_or_url: str = "",
    ctx: Context = None
) -> str:
    """
    Fetch all existing inline comment threads for a Gerrit change and report
    the count of unresolved vs resolved comments per file.
    """
    try:
        raw_input = url or change_id or target or change_id_or_url
        if not raw_input:
            return "❌ Please provide a Gerrit Change URL or Change ID number."

        change_num = _extract_change_id(raw_input)
        comments_data = _gerrit_get(f"changes/{change_num}/comments", ctx=ctx)

        if not comments_data:
            return f"📋 No inline comments found on Gerrit change **{change_num}**."

        total_unresolved = 0
        total_resolved = 0
        file_summaries = []

        for filepath, comments in comments_data.items():
            file_unresolved = 0
            file_resolved = 0
            comment_details = []

            for comment in comments:
                author = comment.get("author", {}).get("name", "Unknown")
                line = comment.get("line", "N/A")
                message = comment.get("message", "")
                unresolved = comment.get("unresolved", False)
                updated = comment.get("updated", "")

                if unresolved:
                    file_unresolved += 1
                    total_unresolved += 1
                    status = "⚠️ Unresolved"
                else:
                    file_resolved += 1
                    total_resolved += 1
                    status = "✅ Resolved"

                comment_details.append({
                    "author": author,
                    "line": line,
                    "message": message[:100],
                    "status": status,
                    "updated": updated
                })

            file_summaries.append({
                "file": filepath,
                "unresolved": file_unresolved,
                "resolved": file_resolved,
                "details": comment_details
            })

        output = (
            f"📋 **Comment Status for Gerrit Change {change_num}**:\n\n"
            f"- **Total Unresolved**: ⚠️ {total_unresolved}\n"
            f"- **Total Resolved**: ✅ {total_resolved}\n\n"
            f"| File | Unresolved | Resolved |\n"
            f"| :--- | :---: | :---: |\n"
        )

        for fs in file_summaries:
            output += f"| `{fs['file']}` | ⚠️ {fs['unresolved']} | ✅ {fs['resolved']} |\n"

        output += "\n---\n\n**Comment Details:**\n\n"

        for fs in file_summaries:
            output += f"### 📄 `{fs['file']}`:\n\n"
            for cd in fs["details"]:
                output += (
                    f"- **Line {cd['line']}** by **{cd['author']}** — {cd['status']}\n"
                    f"  > {cd['message']}\n\n"
                )

        return output
    except Exception as e:
        return f"Error executing get_gerrit_comments: {str(e)}"


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

if __name__ == "__main__":
    import uvicorn
    print(f"Starting Code Review Agent MCP Server on port 8000 (SSE Transport)...")
    print(f"Gerrit URL: {GERRIT_URL}")

    # Wrap Starlette app with HostHeaderBypassMiddleware
    wrapped_app = HostHeaderBypassMiddleware(app)

    uvicorn.run(wrapped_app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")
