import os
import re
import requests
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
        raise ImportError("Failed to import FastMCP. Please ensure 'mcp[cli]' or 'fastmcp' is installed via pip.")

# Initialize FastMCP server
mcp = FastMCP("Jira Data Center MCP Server")

# Default Jira Base URL for Jira Data Center (On-Prem) with /issue context path
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "http://jira.lge.com/issue").rstrip("/")
DEFAULT_JIRA_PAT = os.environ.get("JIRA_PAT", "")

def _markdown_to_jira_markup(text: str) -> str:
    """
    Converts standard Markdown syntax to Jira Data Center Wiki markup.
    In Jira Data Center:
      - '### Heading' is parsed as a 3rd level numbered list ('1. 1. 1. Heading')!
      - 'h3. Heading' is parsed as a real H3 heading.
      - '```lang ... ```' is parsed as '{code:lang} ... {code}'.
    """
    if not text:
        return text
    
    # 1. Convert markdown headings (#, ##, ###, ####, #####, ######) to h1., h2., h3., etc.
    text = re.sub(r'^(#{1,6})\s+(.+)$', lambda m: f"h{len(m.group(1))}. {m.group(2)}", text, flags=re.MULTILINE)
    
    # 2. Convert markdown code blocks ```lang ... ``` to Jira {code:lang} ... {code}
    def _code_block_repl(m):
        lang = m.group(1) or ""
        code = m.group(2).strip("\r\n")
        if lang:
            return f"{{code:{lang}}}\n{code}\n{{code}}"
        return f"{{code}}\n{code}\n{{code}}"
    
    text = re.sub(r'```(\w+)?\r?\n([\s\S]*?)```', _code_block_repl, text)
    
    # 3. Convert markdown inline code `code` to Jira {{code}}
    text = re.sub(r'`([^`\r\n]+)`', r'{{\1}}', text)
    
    # 4. Convert markdown bold **text** to Jira *text*
    text = re.sub(r'\*\*([^*\r\n]+)\*\*', r'*\1*', text)
    
    return text

def get_jira_headers(ctx: Context = None, request: Request = None) -> dict:
    """
    Extract Personal Access Token (PAT) from incoming request context headers
    or fallback to default environment variable JIRA_PAT.
    """
    pat = DEFAULT_JIRA_PAT
    
    # Try extracting X-Jira-PAT from request headers if present
    if ctx and hasattr(ctx, "request_context") and ctx.request_context:
        req: Request = getattr(ctx.request_context, "request", None)
        if req and "x-jira-pat" in req.headers:
            pat = req.headers["x-jira-pat"]
    elif request and "x-jira-pat" in request.headers:
        pat = request.headers["x-jira-pat"]

    if not pat:
        raise ValueError("Missing Jira PAT. Please set 'X-Jira-PAT' in your mcp.json headers or environment variable 'JIRA_PAT'.")

    return {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

_FIELD_CACHE = None

def _get_dynamic_mapping(headers: dict) -> dict:
    global _FIELD_CACHE
    if _FIELD_CACHE is not None:
        return _FIELD_CACHE
        
    base_mapping = {
        "due_date": "duedate",
        "original_estimate": "timetracking",
        "time_spent": "timespent",
        "sprint": "customfield_10005",
        "epic_link": "customfield_11579"
    }
    
    try:
        if headers:
            url = f"{JIRA_BASE_URL}/rest/api/2/field"
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                for f in response.json():
                    name_clean = f.get("name", "").lower().replace(" ", "_")
                    field_id = f.get("id", "")
                    if name_clean and field_id.startswith("customfield_") and name_clean not in base_mapping:
                        base_mapping[name_clean] = field_id
                _FIELD_CACHE = base_mapping
    except Exception:
        pass
        
    return _FIELD_CACHE if _FIELD_CACHE else base_mapping

def _translate_fields(fields: dict, headers: dict = None, project_key: str = None) -> dict:
    """Translates user-friendly field names to Jira custom field IDs dynamically.
    Also handles component/components and fix_version string-to-dict conversion."""
    mapping = _get_dynamic_mapping(headers)
    translated = {}
    for k, v in fields.items():
        key_lower = k.lower().replace(" ", "_")
        mapped_key = mapping.get(key_lower, k)
        
        # Handle sprint "active" resolution
        if key_lower == "sprint" and str(v).lower() == "active" and headers and project_key:
            active_sprint_id = _get_active_sprint_id(project_key, headers)
            if active_sprint_id:
                translated[mapped_key] = active_sprint_id
            else:
                translated[mapped_key] = v
        # Handle component/components: convert string name to [{"name": "..."}] format
        elif key_lower in ("component", "components"):
            if isinstance(v, str):
                translated["components"] = [{"name": v}]
            elif isinstance(v, list) and v and isinstance(v[0], str):
                translated["components"] = [{"name": name} for name in v]
            else:
                translated["components"] = v
        # Handle fix_version/fix_versions: convert string to [{"name": "..."}] format
        elif key_lower in ("fix_version", "fix_versions", "fixversions"):
            if isinstance(v, str):
                translated["fixVersions"] = [{"name": v}]
            elif isinstance(v, list) and v and isinstance(v[0], str):
                translated["fixVersions"] = [{"name": name} for name in v]
            else:
                translated["fixVersions"] = v
        # Handle original_estimate: wrap in timetracking object
        elif key_lower == "original_estimate":
            translated["timetracking"] = {"originalEstimate": v}
        # Handle resolution: wrap in dict
        elif key_lower == "resolution":
            if isinstance(v, str):
                translated["resolution"] = {"name": v}
            else:
                translated["resolution"] = v
        else:
            translated[mapped_key] = v
    return translated

def _format_attachments(attachments: list) -> str:
    if not attachments:
        return "None"
    lines = []
    for att in attachments:
        name = att.get("filename", "unknown")
        size_bytes = att.get("size", 0)
        size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1024 * 1024 else f"{size_bytes / (1024*1024):.2f} MB"
        author = att.get("author", {}).get("displayName", "Unknown")
        created = att.get("created", "")[:10]
        url = att.get("content", "")
        lines.append(f"- 📎 [{name}]({url}) ({size_str}, by {author} on {created})")
    return "\n".join(lines)

@mcp.tool()
def get_jira_issue(issue_key: str, ctx: Context = None) -> str:
    """
    Fetch details of a specific Jira issue by key (e.g., 'PROJ-123').
    """
    try:
        headers = get_jira_headers(ctx)
        url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key.strip().upper()}"
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code != 200:
            return f"Failed to fetch issue '{issue_key}' (HTTP {response.status_code}): {response.text}"

        data = response.json()
        fields = data.get("fields", {})
        summary = fields.get("summary", "No summary")
        status = fields.get("status", {}).get("name", "Unknown")
        issue_type = fields.get("issuetype", {}).get("name", "Task")
        assignee = fields.get("assignee")
        assignee_name = assignee.get("displayName") if assignee else "Unassigned"
        reporter = fields.get("reporter")
        reporter_name = reporter.get("displayName") if reporter else "Unknown"
        description = fields.get("description", "No description provided.")

        sprint_info = fields.get("customfield_10005")
        sprint = sprint_info[0].get("name") if isinstance(sprint_info, list) and sprint_info and isinstance(sprint_info[0], dict) else sprint_info
        epic_link = fields.get("customfield_11579", "None")
        ax_phase = fields.get("customfield_46609", "None")
        ax_save = fields.get("customfield_47009", "None")
        story_points = fields.get("customfield_10002", "None")
        original_story_points = fields.get("customfield_20403", "None")
        priority = fields.get("priority", {}).get("name", "None")
        labels = ", ".join(fields.get("labels", [])) or "None"
        components = ", ".join([c.get("name") for c in fields.get("components", [])]) or "None"
        fix_versions = ", ".join([v.get("name", "") for v in fields.get("fixVersions", [])]) or "None"
        due_date = fields.get("duedate", "None")
        start_date = fields.get("customfield_23191", "None")
        resolution = fields.get("resolution")
        resolution_name = resolution.get("name") if isinstance(resolution, dict) else (resolution or "Unresolved")
        time_tracking = fields.get("timetracking", {})
        original_estimate = time_tracking.get("originalEstimate", "None") if isinstance(time_tracking, dict) else "None"
        time_spent = time_tracking.get("timeSpent", "None") if isinstance(time_tracking, dict) else "None"
        attachments_str = _format_attachments(fields.get("attachment", []))

        return (
            f"🎫 **[{data.get('key')}] {summary}**\n"
            f"- **Type**: {issue_type}\n"
            f"- **Status**: {status}\n"
            f"- **Resolution**: {resolution_name}\n"
            f"- **Priority**: {priority}\n"
            f"- **Assignee**: {assignee_name}\n"
            f"- **Reporter**: {reporter_name}\n"
            f"- **Sprint**: {sprint}\n"
            f"- **Epic Link**: {epic_link}\n"
            f"- **Story Points**: {story_points}\n"
            f"- **Original Story Points**: {original_story_points}\n"
            f"- **AX_phase**: {ax_phase}\n"
            f"- **AX_Save**: {ax_save}\n"
            f"- **Labels**: {labels}\n"
            f"- **Component**: {components}\n"
            f"- **Fix Version/s**: {fix_versions}\n"
            f"- **Start Date**: {start_date}\n"
            f"- **Due Date**: {due_date}\n"
            f"- **Original Estimate**: {original_estimate}\n"
            f"- **Time Spent**: {time_spent}\n"
            f"- **Attachments**:\n{attachments_str}\n"
            f"- **URL**: {JIRA_BASE_URL}/browse/{data.get('key')}\n\n"
            f"**Description**:\n{description[:500]}..."
        )
    except Exception as e:
        return f"Error executing get_jira_issue: {str(e)}"

@mcp.tool()
def search_jira_issues(jql: str, max_results: int = 25, ctx: Context = None) -> str:
    """
    Search Jira Data Center issues using JQL (e.g., 'project = PROJ AND status = "In Progress"').
    """
    try:
        headers = get_jira_headers(ctx)
        url = f"{JIRA_BASE_URL}/rest/api/2/search"
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "status", "assignee", "issuetype", "customfield_10002", "priority"]
        }
        response = requests.post(url, headers=headers, json=payload, timeout=15)

        if response.status_code != 200:
            return f"JQL Search failed (HTTP {response.status_code}): {response.text}"

        data = response.json()
        issues = data.get("issues", [])
        if not issues:
            return f"No Jira issues found matching query: `{jql}`"

        status_counts = {}
        total_points = 0.0

        output = [f"Found {len(issues)} issue(s) for query `{jql}`:"]
        for issue in issues:
            key = issue.get("key")
            fields = issue.get("fields", {})
            summary = fields.get("summary", "")
            status = fields.get("status", {}).get("name", "")
            priority = fields.get("priority", {}).get("name", "None")
            assignee = fields.get("assignee")
            assignee_name = assignee.get("displayName") if assignee else "Unassigned"
            sp = fields.get("customfield_10002")
            
            # Tally status
            status_counts[status] = status_counts.get(status, 0) + 1
            
            # Format Story Points cleanly (e.g. 2.0 -> 2, but keep 2.5 as 2.5)
            sp_display = "Unpointed (-)"
            if sp is not None:
                try:
                    sp_float = float(sp)
                    total_points += sp_float
                    sp_display = f"{int(sp_float)} pts" if sp_float.is_integer() else f"{sp_float} pts"
                except ValueError:
                    sp_display = f"{sp} pts"
            
            output.append(f"- **[{key}]** ({status}) | Assignee: {assignee_name} | Priority: {priority} | Story Points: {sp_display} | {summary} — {JIRA_BASE_URL}/browse/{key}")

        # Provide a server-calculated summary to stop the AI from hallucinating math
        total_pts_display = f"{int(total_points)}" if total_points.is_integer() else f"{total_points}"
        summary_text = " | ".join([f"{k}: {v}" for k, v in status_counts.items()])
        output.append(f"\n**Server-Calculated Summary**: {len(issues)} total stories | {summary_text} | Total Story Points: {total_pts_display}")

        return "\n".join(output)
    except Exception as e:
        return f"Error executing search_jira_issues: {str(e)}"

@mcp.tool()
def create_jira_issue(
    project_key: str, 
    summary: str, 
    description: str = "", 
    issue_type: str = "Task", 
    custom_fields: dict = None,
    ctx: Context = None
) -> str:
    """
    Create a new issue in Jira Data Center with optional custom fields support.
    """
    try:
        headers = get_jira_headers(ctx)
        url = f"{JIRA_BASE_URL}/rest/api/2/issue"
        
        # Default initialization for Sprint and Component
        base_custom_fields = {
            "sprint": "active",
            "component": "2026_HS_GPOS_PLATFORM"
        }
        
        # Only add AX fields for 'story' to prevent Epic/Task/Initiative screen errors
        if issue_type.lower() == "story":
            base_custom_fields["ax_phase"] = "0"
            base_custom_fields["ax_save"] = "0"
        if custom_fields:
            base_custom_fields.update(custom_fields)

        # Force strip AX fields if issue type is not a Story, regardless of what the LLM passes
        if issue_type.lower() != "story":
            base_custom_fields.pop("ax_phase", None)
            base_custom_fields.pop("ax_save", None)
            base_custom_fields.pop("customfield_46609", None)
            base_custom_fields.pop("customfield_47009", None)

        translated_fields = _translate_fields(base_custom_fields, headers, project_key)

        payload = {
            "fields": {
                "project": {"key": project_key.strip().upper()},
                "summary": summary,
                "description": description,
                "issuetype": {"name": issue_type}
            }
        }

        # Merge custom fields
        if translated_fields:
            payload["fields"].update(translated_fields)

        response = requests.post(url, headers=headers, json=payload, timeout=15)

        if response.status_code not in (200, 201):
            return f"Failed to create Jira issue (HTTP {response.status_code}): {response.text}"

        data = response.json()
        key = data.get("key")
        return f"✅ **Successfully created Jira Issue [{key}]**!\nLink: {JIRA_BASE_URL}/browse/{key}"
    except Exception as e:
        return f"Error executing create_jira_issue: {str(e)}"

@mcp.tool()
def add_jira_comment(issue_key: str, comment_text: str, ctx: Context = None) -> str:
    """
    Add a comment to an existing Jira ticket under your user identity.

    CRITICAL INSTRUCTIONS FOR AI MODELS (READ CAREFULLY BEFORE CALLING):
    1. 🛑 2-PHASE CONFIRMATION MANDATE: You MUST NOT invoke this tool on your FIRST response!
       Your first response in chat MUST ONLY display the drafted comment text to the user and ask:
       "Reply 1 to Post, or 2 to Cancel."
       You are STRICTLY FORBIDDEN from calling this tool until the user explicitly replies with '1' or positive confirmation.

    2. 📝 MANDATORY COMMENT FORMAT: The comment_text parameter MUST strictly follow this exact clean layout:
       ### 📌 Work Summary
       <1-2 sentences overview of the work done>

       **AI Contribution**:
       - <bullet points of AI generation, research, or testing>

       **Developer Contribution**:
       - <bullet points of developer review, integration, or implementation>

       (DO NOT use numbered list prefixes like "1. Work Summary" or "1. 1. Work Summary").

    3. 🔍 CONTEXT FETCHING: If the user did NOT provide explicit comment text, call get_jira_issue
       or get_jira_comments FIRST to read the ticket's summary and description, then draft a meaningful comment.
    """
    try:
        # Code-level Guard: Reject any comment missing mandatory sections
        lower_text = comment_text.lower()
        if "ai contribution" not in lower_text or "developer contribution" not in lower_text:
            return (
                "❌ REJECTED BY MCP SERVER FORMATTING POLICY:\n"
                "Your comment text is missing mandatory sections ('AI Contribution' and 'Developer Contribution').\n\n"
                "You MUST format comments strictly as follows:\n"
                "### 📌 Work Summary\n<1-2 sentences overview>\n\n"
                "**AI Contribution**:\n- <bullet points>\n\n"
                "**Developer Contribution**:\n- <bullet points>\n\n"
                "Please draft the reformatted comment in chat and ask the user for confirmation ('Reply 1 to Post, or 2 to Cancel')."
            )

        headers = get_jira_headers(ctx)
        url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key.strip().upper()}/comment"
        # Convert standard markdown (###, **, ```) to Jira Data Center wiki syntax (h3., *, {code})
        jira_formatted_body = _markdown_to_jira_markup(comment_text)
        payload = {"body": jira_formatted_body}
        response = requests.post(url, headers=headers, json=payload, timeout=15)

        if response.status_code not in (200, 201):
            return f"Failed to add comment (HTTP {response.status_code}): {response.text}"

        return f"💬 Successfully added comment to Jira ticket **{issue_key}**!"
    except Exception as e:
        return f"Error executing add_jira_comment: {str(e)}"

@mcp.tool()
def list_jira_fields(search_term: str = "", custom_only: bool = True, ctx: Context = None) -> str:
    """
    Discover all available Jira fields (standard and custom) and their internal IDs.
    Use this to find the correct customfield_XXXXX ID for company-specific fields
    like AX_IMPL, AX_REQ, or any other custom field.

    :param search_term: Optional filter to search fields by name (e.g., 'AX' to find all AX fields).
    :param custom_only: If True (default), only returns custom fields. Set False to include standard fields too.
    """
    try:
        headers = get_jira_headers(ctx)
        url = f"{JIRA_BASE_URL}/rest/api/2/field"
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code != 200:
            return f"Failed to fetch fields (HTTP {response.status_code}): {response.text}"

        all_fields = response.json()

        # Filter fields
        filtered = []
        for field in all_fields:
            is_custom = field.get("custom", False)
            field_name = field.get("name", "")
            field_id = field.get("id", "")
            field_type = field.get("schema", {}).get("type", "unknown") if field.get("schema") else "unknown"

            # Apply custom_only filter
            if custom_only and not is_custom:
                continue

            # Apply search term filter
            if search_term and search_term.lower() not in field_name.lower():
                continue

            filtered.append({
                "name": field_name,
                "id": field_id,
                "type": field_type,
                "custom": is_custom
            })

        if not filtered:
            return f"No fields found matching '{search_term}'."

        # Sort by name
        filtered.sort(key=lambda x: x["name"])

        # Build output table
        output = f"📋 **Jira Fields** (found {len(filtered)} fields"
        if search_term:
            output += f" matching '{search_term}'"
        output += "):\n\n"
        output += "| Field Name | Internal ID | Type | Custom |\n"
        output += "| :--- | :--- | :--- | :--- |\n"

        for f in filtered:
            custom_tag = "✅ Yes" if f["custom"] else "No"
            output += f"| {f['name']} | `{f['id']}` | {f['type']} | {custom_tag} |\n"

        output += (
            f"\n💡 **Usage**: To update a custom field, use its Internal ID.\n"
            f"Example: `update_jira_issue('SIGPOSDEV-1971', {{'customfield_XXXXX': 'value'}})`"
        )

        return output
    except Exception as e:
        return f"Error executing list_jira_fields: {str(e)}"


@mcp.tool()
def update_jira_issue(issue_key: str, fields: dict, ctx: Context = None) -> str:
    """
    Update any fields on an existing Jira issue, including standard fields
    (summary, description, assignee, priority, status, story_points) and
    custom/AX fields (e.g., customfield_10011).

    CRITICAL MANDATE: You MUST prompt the user for 2-Phase Confirmation before calling this tool!
    Display the proposed field updates in chat and ask "Reply 1 to Update, or 2 to Cancel."
    Do NOT execute until confirmed.

    Example fields: {"summary": "New Title", "assignee": {"name": "john.doe"},
                     "priority": {"name": "High"}, "story_points": 2, "component": "2026_HS_GPOS_PLATFORM"}
    """
    try:
        headers = get_jira_headers(ctx)
        url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key.strip().upper()}"
        
        project_key = issue_key.split("-")[0] if "-" in issue_key else None
        translated_fields = _translate_fields(fields, headers, project_key)
        
        payload = {"fields": translated_fields}
        response = requests.put(url, headers=headers, json=payload, timeout=15)

        if response.status_code not in (200, 204):
            return f"Failed to update issue '{issue_key}' (HTTP {response.status_code}): {response.text}"

        updated_fields = ", ".join(fields.keys())
        return f"✅ Successfully updated Jira Issue **[{issue_key}]**!\nUpdated fields: {updated_fields}"
    except Exception as e:
        return f"Error executing update_jira_issue: {str(e)}"


@mcp.tool()
def transition_jira_issue(issue_key: str, target_status: str, ctx: Context = None) -> str:
    """
    Transition a Jira issue to a new workflow status (e.g., 'In Progress', 'Resolved', 'Closed', 'Reopened', 'To Do', 'Open').
    
    CRITICAL MANDATE: You MUST prompt the user for 2-Phase Confirmation in chat before calling this tool!
    Display the drafted action: "I will transition [KEY] to status 'target_status'. Reply 1 to Confirm, or 2 to Cancel."
    Do NOT execute until confirmed.
    """
    try:
        headers = get_jira_headers(ctx)
        key = issue_key.strip().upper()
        
        # Step 1: Fetch available transitions for this ticket
        trans_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{key}/transitions"
        res = requests.get(trans_url, headers=headers, timeout=15)
        if res.status_code != 200:
            return f"Failed to fetch transitions for '{key}' (HTTP {res.status_code}): {res.text}"
            
        transitions = res.json().get("transitions", [])
        if not transitions:
            return f"⚠️ No available workflow transitions found for ticket **[{key}]**."
            
        # Step 2: Match target_status against transition names / to.name
        matched_id = None
        matched_name = None
        target_clean = target_status.strip().lower()
        
        for t in transitions:
            t_name = t.get("name", "")
            to_name = t.get("to", {}).get("name", "")
            if target_clean in t_name.lower() or target_clean in to_name.lower():
                matched_id = t.get("id")
                matched_name = to_name or t_name
                break
                
        if not matched_id:
            available_names = [f"'{t.get('name')}' (to {t.get('to', {}).get('name')})" for t in transitions]
            return f"❌ Could not match status '{target_status}'. Available transitions for [{key}] are:\n- " + "\n- ".join(available_names)
            
        # Step 3: Execute transition
        payload = {"transition": {"id": matched_id}}
        post_res = requests.post(trans_url, headers=headers, json=payload, timeout=15)
        if post_res.status_code not in (200, 204):
            return f"Failed to transition issue '{key}' (HTTP {post_res.status_code}): {post_res.text}"
            
        return f"🚀 Successfully transitioned Jira Issue **[{key}]** to **{matched_name}**!\nLink: {JIRA_BASE_URL}/browse/{key}"
    except Exception as e:
        return f"Error executing transition_jira_issue: {str(e)}"


@mcp.tool()
def log_jira_work(issue_key: str, time_spent: str, comment: str = "", started: str = None, ctx: Context = None) -> str:
    """
    Log work time on a Jira issue (e.g., '2h', '1d 4h', '30m').
    
    :param issue_key: The Jira issue key (e.g., 'SIGPOSDEV-2278').
    :param time_spent: Time spent formatted as Jira time string (e.g., '2h', '30m', '1d').
    :param comment: Optional comment explaining the work done.
    :param started: Optional ISO timestamp or date when work started (defaults to now).
    
    CRITICAL MANDATE: You MUST prompt the user for 2-Phase Confirmation in chat before calling this tool!
    Display the logged time and comment, then ask: "Reply 1 to Log Work, or 2 to Cancel."
    """
    try:
        headers = get_jira_headers(ctx)
        key = issue_key.strip().upper()
        url = f"{JIRA_BASE_URL}/rest/api/2/issue/{key}/worklog"
        
        payload = {"timeSpent": time_spent.strip()}
        if comment:
            payload["comment"] = _markdown_to_jira_markup(comment)
        if started:
            payload["started"] = started
            
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        if res.status_code not in (200, 201):
            return f"Failed to log work on issue '{key}' (HTTP {res.status_code}): {res.text}"
            
        msg = f"⏱️ Successfully logged **{time_spent}** on Jira Issue **[{key}]**!"
        if comment:
            msg += f"\nComment: *{comment}*"
        msg += f"\nLink: {JIRA_BASE_URL}/browse/{key}"
        return msg
    except Exception as e:
        return f"Error executing log_jira_work: {str(e)}"


@mcp.tool()
def get_jira_comments(issue_key: str, ctx: Context = None) -> str:
    """
    Fetch the complete context of a Jira ticket including its Title, Description,
    Definition of Done (DOD), and full chronological comment history.
    This provides the complete conversation thread so you can understand the full
    discussion context and reply accurately to the latest comment.
    """
    try:
        headers = get_jira_headers(ctx)
        key = issue_key.strip().upper()

        # Step 1: Fetch the issue details (title, description, DOD)
        issue_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{key}"
        issue_response = requests.get(issue_url, headers=headers, timeout=15)

        if issue_response.status_code != 200:
            return f"Failed to fetch issue '{key}' (HTTP {issue_response.status_code}): {issue_response.text}"

        issue_data = issue_response.json()
        issue_fields = issue_data.get("fields", {})
        summary = issue_fields.get("summary", "No summary")
        description = issue_fields.get("description", "No description provided.")
        status = issue_fields.get("status", {}).get("name", "Unknown")
        issue_type = issue_fields.get("issuetype", {}).get("name", "Task")
        assignee = issue_fields.get("assignee")
        assignee_name = assignee.get("displayName") if assignee else "Unassigned"

        sprint_info = issue_fields.get("customfield_10005")
        sprint = sprint_info[0].get("name") if isinstance(sprint_info, list) and sprint_info and isinstance(sprint_info[0], dict) else sprint_info
        epic_link = issue_fields.get("customfield_11579", "None")
        ax_phase = issue_fields.get("customfield_46609", "None")
        ax_save = issue_fields.get("customfield_47009", "None")
        story_points = issue_fields.get("customfield_10002", "None")
        original_story_points = issue_fields.get("customfield_20403", "None")
        priority = issue_fields.get("priority", {}).get("name", "None")
        labels = ", ".join(issue_fields.get("labels", [])) or "None"
        components = ", ".join([c.get("name") for c in issue_fields.get("components", [])]) or "None"
        fix_versions = ", ".join([v.get("name", "") for v in issue_fields.get("fixVersions", [])]) or "None"
        due_date = issue_fields.get("duedate", "None")
        start_date = issue_fields.get("customfield_23191", "None")
        resolution = issue_fields.get("resolution")
        resolution_name = resolution.get("name") if isinstance(resolution, dict) else (resolution or "Unresolved")
        time_tracking = issue_fields.get("timetracking", {})
        original_estimate = time_tracking.get("originalEstimate", "None") if isinstance(time_tracking, dict) else "None"
        time_spent = time_tracking.get("timeSpent", "None") if isinstance(time_tracking, dict) else "None"

        # Try to extract DOD from common custom field locations
        dod = ""
        if "definition of done" in (description or "").lower():
            dod = "See Description above (contains DOD)."

        # Step 2: Fetch all comments in chronological order
        comments_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{key}/comment?orderBy=created"
        comments_response = requests.get(comments_url, headers=headers, timeout=15)

        comments_section = ""
        if comments_response.status_code == 200:
            comments_data = comments_response.json()
            comments = comments_data.get("comments", [])

            if comments:
                comment_lines = []
                for i, comment in enumerate(comments, 1):
                    c_id = comment.get("id", "Unknown")
                    author = comment.get("author", {}).get("displayName", "Unknown")
                    created = comment.get("created", "Unknown date")
                    body = comment.get("body", "")
                    comment_lines.append(
                        f"**Comment #{i}** (ID: `{c_id}`) by **{author}** ({created}):\n{body}"
                    )
                comments_section = "\n\n---\n\n".join(comment_lines)
            else:
                comments_section = "No comments yet."
        else:
            comments_section = f"Failed to fetch comments (HTTP {comments_response.status_code})."

        attachments_str = _format_attachments(issue_fields.get("attachment", []))

        # Build the full context output
        output = (
            f"🎫 **[{key}] {summary}**\n"
            f"- **Type**: {issue_type}\n"
            f"- **Status**: {status}\n"
            f"- **Resolution**: {resolution_name}\n"
            f"- **Priority**: {priority}\n"
            f"- **Assignee**: {assignee_name}\n"
            f"- **Sprint**: {sprint}\n"
            f"- **Epic Link**: {epic_link}\n"
            f"- **Story Points**: {story_points}\n"
            f"- **Original Story Points**: {original_story_points}\n"
            f"- **AX_phase**: {ax_phase}\n"
            f"- **AX_Save**: {ax_save}\n"
            f"- **Labels**: {labels}\n"
            f"- **Component**: {components}\n"
            f"- **Fix Version/s**: {fix_versions}\n"
            f"- **Start Date**: {start_date}\n"
            f"- **Due Date**: {due_date}\n"
            f"- **Original Estimate**: {original_estimate}\n"
            f"- **Time Spent**: {time_spent}\n"
            f"- **Attachments**:\n{attachments_str}\n\n"
            f"**Description:**\n{description}\n\n"
        )
        if dod:
            output += f"**Definition of Done (DOD):**\n{dod}\n\n"

        output += f"---\n\n## 💬 Comment History ({len(comments_data.get('comments', []))} comments):\n\n{comments_section}"

        return output
    except Exception as e:
        return f"Error executing get_jira_comments: {str(e)}"


def _get_active_sprint_id(project_key: str, headers: dict) -> int:
    """
    Helper function to resolve the currently active sprint ID for a given project.
    Uses the Jira Agile REST API to find open sprints on the project's board.
    """
    # Step 1: Find the board for the project
    board_url = f"{JIRA_BASE_URL}/rest/agile/1.0/board?projectKeyOrId={project_key}"
    board_response = requests.get(board_url, headers=headers, timeout=15)

    if board_response.status_code != 200:
        return None

    boards = board_response.json().get("values", [])
    if not boards:
        return None

    board_id = boards[0].get("id")

    # Step 2: Find the active sprint on the board
    sprint_url = f"{JIRA_BASE_URL}/rest/agile/1.0/board/{board_id}/sprint?state=active"
    sprint_response = requests.get(sprint_url, headers=headers, timeout=15)

    if sprint_response.status_code != 200:
        return None

    sprints = sprint_response.json().get("values", [])
    if not sprints:
        return None

    return sprints[0].get("id")


@mcp.tool()
def audit_sprint_issues(
    project_key: str = "SIGPOSDEV",
    check_labels: bool = True,
    check_assignee: bool = True,
    check_story_points: bool = True,
    custom_required_labels: list = None,
    jql: str = None,
    ctx: Context = None
) -> str:
    """
    Audit tickets in the currently ACTIVE sprint of a project and report governance violations:
    1. Unassigned tickets (Missing Assignee).
    2. Tickets missing Story Points (customfield_10002).
    3. Tickets missing standard team labels (training, development, operations, Analysis-Done, unplanned_leave, or AX_... labels).
    4. Missing custom labels (if explicitly provided).

    :param project_key: The Jira project key (default: 'SIGPOSDEV').
    :param check_labels: If True (default), verifies tickets have at least one valid category or AX label.
    :param check_assignee: If True (default), flags unassigned tickets.
    :param check_story_points: If True (default), flags tickets missing story points (customfield_10002).
    :param custom_required_labels: Optional specific labels to enforce (e.g. ['training']).
    :param jql: Optional custom JQL query. Defaults to active sprint of project board.
    """
    try:
        headers = get_jira_headers(ctx)
        proj = project_key.strip().upper()

        # Build JQL: resolve actual active sprint ID on project board
        if not jql:
            active_sprint_id = _get_active_sprint_id(proj, headers)
            if active_sprint_id:
                jql = f"project = {proj} AND sprint = {active_sprint_id} ORDER BY key DESC"
            else:
                jql = f"project = {proj} AND sprint in openSprints() ORDER BY key DESC"

        search_url = f"{JIRA_BASE_URL}/rest/api/2/search"

        # Request standard and custom fields (including customfield_10002 for Story Points)
        all_field_names = [
            "summary", "status", "assignee", "labels", "priority", 
            "issuetype", "customfield_10002", "customfield_46609"
        ]

        payload = {
            "jql": jql,
            "maxResults": 100,
            "fields": all_field_names
        }
        response = requests.post(search_url, headers=headers, json=payload, timeout=30)

        if response.status_code != 200:
            return f"Sprint audit failed (HTTP {response.status_code}): {response.text}"

        data = response.json()
        issues = data.get("issues", [])

        if not issues:
            return f"No issues found in active sprint for project `{proj}`."

        VALID_CATEGORY_LABELS = {
            "training", "development", "analysis-done", "operations", 
            "unplanned_leave", "ax_req", "ax_hld", "ax_sds", "ax_impl", 
            "analysis_done", "code_merged"
        }

        # Audit each issue
        violations = []
        for issue in issues:
            key = issue.get("key")
            f = issue.get("fields", {})
            issue_summary = f.get("summary", "")
            assignee = f.get("assignee")
            assignee_name = assignee.get("displayName") if assignee else "⚠️ Unassigned"
            raw_labels = f.get("labels", [])
            issue_labels_lower = [l.lower() for l in raw_labels]
            story_points = f.get("customfield_10002")

            missing_items = []

            # 1. Check Assignee
            if check_assignee and not assignee:
                missing_items.append("Missing Assignee")

            # 2. Check Story Points (customfield_10002)
            if check_story_points:
                if story_points is None or story_points == "" or story_points == 0:
                    missing_items.append("Missing Story Points")

            # 3. Check Standard Team / AX Labels
            if check_labels:
                has_valid_label = any(vl in issue_labels_lower for vl in VALID_CATEGORY_LABELS)
                if not has_valid_label:
                    missing_items.append("Missing Category/AX Label")

            # 4. Check specific custom labels if user explicitly requested them
            if custom_required_labels:
                for req_label in custom_required_labels:
                    if req_label.lower() not in issue_labels_lower:
                        missing_items.append(f"Missing `{req_label}`")

            if missing_items:
                display_labels = ", ".join(raw_labels) if raw_labels else "None"
                violations.append(
                    f"| **[{key}]({JIRA_BASE_URL}/browse/{key})** | {issue_summary[:45]} | {assignee_name} | {display_labels} | {', '.join(missing_items)} |"
                )

        if not violations:
            return (
                f"✅ **Sprint Governance Audit PASSED** for project `{proj}`!\n"
                f"All {len(issues)} active sprint tickets have valid labels, assignees, and story points."
            )

        report = (
            f"⚠️ **Sprint Governance Audit Report** for `{proj}` ({len(violations)} of {len(issues)} tickets need attention):\n\n"
            f"| Ticket | Summary | Assignee | Current Labels | Missing Items |\n"
            f"| :--- | :--- | :--- | :--- | :--- |\n"
        )
        report += "\n".join(violations)
        report += f"\n\n**Summary**: {len(violations)} out of {len(issues)} tickets have missing labels, story points, or assignees."

        return report
    except Exception as e:
        return f"Error executing audit_sprint_issues: {str(e)}"


@mcp.tool()
def generate_sprint_report(
    project_key: str = "SIGPOSDEV",
    sprint_name: str = None,
    ctx: Context = None,
) -> str:
    """
    Generate a comprehensive Sprint Report for the given project.
    This tool fetches ALL tickets in the active (or specified) sprint and computes
    real aggregated metrics server-side. No AI estimation is involved — all numbers
    are calculated from actual Jira data.

    Parameters:
    - project_key: The Jira project key (default: SIGPOSDEV).
    - sprint_name: (Optional) Specific sprint name. If omitted, the active sprint is used.

    Output includes:
    - Sprint Overview (total tickets, points planned/completed/in-progress/to-do)
    - Completion Percentage
    - Per-Developer Breakdown table
    - Issue Type Distribution
    - At-Risk Items (unassigned, 0-point, blocked)
    """
    try:
        headers = get_jira_headers(ctx)

        # --- 1. Resolve Sprint ---
        sprint_id = None
        resolved_sprint_name = sprint_name

        if not sprint_name:
            sprint_id = _get_active_sprint_id(project_key, headers)
            if not sprint_id:
                return f"❌ No active sprint found for project '{project_key}'."
        
        # Build JQL
        if sprint_id:
            jql = f"project = {project_key} AND sprint = {sprint_id}"
        else:
            jql = f'project = {project_key} AND sprint = "{sprint_name}"'

        # --- 2. Fetch ALL issues (paginated) ---
        all_issues = []
        start_at = 0
        max_per_page = 100
        fields = "summary,status,assignee,issuetype,customfield_10002,labels,components,priority,resolution,fixVersions,duedate,timetracking,customfield_20403"

        while True:
            search_url = (
                f"{JIRA_BASE_URL}/rest/api/2/search"
                f"?jql={requests.utils.quote(jql)}"
                f"&startAt={start_at}&maxResults={max_per_page}"
                f"&fields={fields}"
            )
            resp = requests.get(search_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                return f"❌ Failed to fetch sprint issues (HTTP {resp.status_code}): {resp.text}"
            
            data = resp.json()
            batch = data.get("issues", [])
            all_issues.extend(batch)
            
            if start_at + len(batch) >= data.get("total", 0):
                break
            start_at += max_per_page

        total_issues = len(all_issues)
        if total_issues == 0:
            return f"ℹ️ Sprint has 0 issues for project '{project_key}'."

        # --- 3. Resolve sprint name for header ---
        if not resolved_sprint_name and all_issues:
            # Try to get sprint name from the first issue's sprint field
            first_fields = all_issues[0].get("fields", {})
            sprint_info = first_fields.get("customfield_10005")
            if isinstance(sprint_info, list) and sprint_info:
                if isinstance(sprint_info[0], dict):
                    resolved_sprint_name = sprint_info[0].get("name", f"Sprint ID {sprint_id}")
                else:
                    resolved_sprint_name = str(sprint_info[0])
            else:
                resolved_sprint_name = f"Sprint ID {sprint_id}"

        # --- 4. Compute Aggregations ---
        # Status buckets
        DONE_STATUSES = {"done", "closed", "resolved", "verified", "complete", "released"}
        IN_PROGRESS_STATUSES = {"in progress", "in review", "in development", "code review", "testing", "in testing", "review"}

        total_points_planned = 0.0
        total_points_done = 0.0
        total_points_in_progress = 0.0
        total_points_todo = 0.0

        tickets_done = 0
        tickets_in_progress = 0
        tickets_todo = 0

        # Per-developer stats: {name: {tickets, points, done_pts, ip_pts, todo_pts, done_count, ip_count, todo_count}}
        dev_stats = {}
        # Issue type distribution
        type_dist = {}
        # At-risk items
        unassigned_tickets = []
        zero_point_tickets = []
        blocked_tickets = []

        for issue in all_issues:
            key = issue.get("key", "")
            f = issue.get("fields", {})
            summary = f.get("summary", "")[:50]
            status_name = f.get("status", {}).get("name", "Unknown")
            status_lower = status_name.lower()
            assignee_obj = f.get("assignee")
            assignee_name = assignee_obj.get("displayName") if assignee_obj else "Unassigned"
            issue_type = f.get("issuetype", {}).get("name", "Task")
            sp = f.get("customfield_10002")
            story_points = float(sp) if sp is not None else 0.0

            total_points_planned += story_points

            # Classify by status
            if status_lower in DONE_STATUSES:
                total_points_done += story_points
                tickets_done += 1
                bucket = "done"
            elif status_lower in IN_PROGRESS_STATUSES:
                total_points_in_progress += story_points
                tickets_in_progress += 1
                bucket = "in_progress"
            else:
                total_points_todo += story_points
                tickets_todo += 1
                bucket = "todo"

            # Per-developer
            if assignee_name not in dev_stats:
                dev_stats[assignee_name] = {
                    "tickets": 0, "points": 0.0,
                    "done_pts": 0.0, "ip_pts": 0.0, "todo_pts": 0.0,
                    "done_count": 0, "ip_count": 0, "todo_count": 0
                }
            ds = dev_stats[assignee_name]
            ds["tickets"] += 1
            ds["points"] += story_points
            if bucket == "done":
                ds["done_pts"] += story_points
                ds["done_count"] += 1
            elif bucket == "in_progress":
                ds["ip_pts"] += story_points
                ds["ip_count"] += 1
            else:
                ds["todo_pts"] += story_points
                ds["todo_count"] += 1

            # Issue type distribution
            type_dist[issue_type] = type_dist.get(issue_type, 0) + 1

            # At-risk detection
            if not assignee_obj:
                unassigned_tickets.append(f"{key}: {summary}")
            if story_points == 0:
                zero_point_tickets.append(f"{key}: {summary}")
            if status_lower in ("blocked", "impediment"):
                blocked_tickets.append(f"{key}: {summary}")

        # --- 5. Build Report ---
        completion_pct = (total_points_done / total_points_planned * 100) if total_points_planned > 0 else 0
        ticket_completion_pct = (tickets_done / total_issues * 100) if total_issues > 0 else 0

        report = f"# 📊 Sprint Report: {resolved_sprint_name}\n"
        report += f"**Project**: {project_key} | **Total Tickets**: {total_issues}\n\n"

        # Overview table
        report += "## 📈 Sprint Overview\n\n"
        report += "| Metric | Tickets | Story Points |\n"
        report += "| :--- | :---: | :---: |\n"
        report += f"| ✅ Done | {tickets_done} | {total_points_done:.1f} |\n"
        report += f"| 🔄 In Progress | {tickets_in_progress} | {total_points_in_progress:.1f} |\n"
        report += f"| 📋 To Do | {tickets_todo} | {total_points_todo:.1f} |\n"
        report += f"| **Total Planned** | **{total_issues}** | **{total_points_planned:.1f}** |\n\n"

        # Completion bar
        filled = int(completion_pct // 5)
        bar = "█" * filled + "░" * (20 - filled)
        report += f"**Sprint Completion**: [{bar}] {completion_pct:.1f}% (by points) | {ticket_completion_pct:.1f}% (by tickets)\n\n"

        # Visual Mermaid Pie Charts
        report += "### 🥧 Status Breakdown\n```mermaid\npie title Sprint Status\n"
        if tickets_done > 0:
            report += f'    "Done" : {tickets_done}\n'
        if tickets_in_progress > 0:
            report += f'    "In Progress" : {tickets_in_progress}\n'
        if tickets_todo > 0:
            report += f'    "To Do" : {tickets_todo}\n'
        report += "```\n\n"

        # Per-developer breakdown
        report += "---\n\n## 👥 Per-Developer Breakdown\n\n"
        report += "| Developer | Tickets | Points | ✅ Done | 🔄 In Progress | 📋 To Do |\n"
        report += "| :--- | :---: | :---: | :---: | :---: | :---: |\n"

        for dev_name in sorted(dev_stats.keys()):
            ds = dev_stats[dev_name]
            report += (
                f"| {dev_name} | {ds['tickets']} | {ds['points']:.1f} "
                f"| {ds['done_count']} ({ds['done_pts']:.1f} pts) "
                f"| {ds['ip_count']} ({ds['ip_pts']:.1f} pts) "
                f"| {ds['todo_count']} ({ds['todo_pts']:.1f} pts) |\n"
            )

        # Developer points pie chart
        dev_pts_entries = [f'    "{d} ({dev_stats[d]["points"]:.0f} pts)" : {max(1, int(dev_stats[d]["points"]))}' for d in sorted(dev_stats.keys()) if dev_stats[d]["points"] > 0]
        if dev_pts_entries:
            report += "\n```mermaid\npie title Story Points by Developer\n" + "\n".join(dev_pts_entries) + "\n```\n"

        # Issue type distribution
        report += "\n---\n\n## 📂 Issue Type Distribution\n\n"
        report += "| Type | Count |\n"
        report += "| :--- | :---: |\n"
        for itype, count in sorted(type_dist.items(), key=lambda x: -x[1]):
            report += f"| {itype} | {count} |\n"

        # At-risk items
        report += "\n---\n\n## ⚠️ At-Risk Items\n\n"
        if unassigned_tickets:
            report += f"**Unassigned Tickets ({len(unassigned_tickets)}):**\n"
            for t in unassigned_tickets[:15]:
                report += f"- {t}\n"
            if len(unassigned_tickets) > 15:
                report += f"- ... and {len(unassigned_tickets) - 15} more\n"
            report += "\n"
        else:
            report += "✅ No unassigned tickets.\n\n"

        if zero_point_tickets:
            report += f"**Zero Story Point Tickets ({len(zero_point_tickets)}):**\n"
            for t in zero_point_tickets[:15]:
                report += f"- {t}\n"
            if len(zero_point_tickets) > 15:
                report += f"- ... and {len(zero_point_tickets) - 15} more\n"
            report += "\n"
        else:
            report += "✅ All tickets have story points.\n\n"

        if blocked_tickets:
            report += f"**Blocked Tickets ({len(blocked_tickets)}):**\n"
            for t in blocked_tickets[:10]:
                report += f"- {t}\n"
            report += "\n"
        else:
            report += "✅ No blocked tickets.\n\n"

        return report

    except Exception as e:
        return f"Error executing generate_sprint_report: {str(e)}"


@mcp.tool()
def get_sprint_burndown(project_key: str = "SIGPOSDEV", sprint_name: str = "", ctx: Context = None) -> str:
    """
    Generate an interactive visual Sprint Burndown chart (Mermaid line chart) and daily progression table
    comparing Ideal Burndown vs Actual Remaining Story Points.
    """
    try:
        headers = get_jira_headers(ctx)
        proj = project_key.strip().upper()
        
        # Step 1: Resolve Sprint ID
        sprint_id = _get_active_sprint_id(proj, headers)
        
        # Step 2: Build JQL
        if sprint_id and not sprint_name:
            jql = f"project = {proj} AND sprint = {sprint_id}"
        elif sprint_name:
            jql = f'project = {proj} AND sprint = "{sprint_name}"'
        else:
            jql = f"project = {proj} AND sprint in openSprints()"

        # Fetch lightweight fields only (fast and prevents timeouts!)
        search_url = (
            f"{JIRA_BASE_URL}/rest/api/2/search"
            f"?jql={requests.utils.quote(jql)}"
            f"&maxResults=100"
            f"&fields=summary,status,assignee,customfield_10002,customfield_10005,resolutiondate"
        )
        s_resp = requests.get(search_url, headers=headers, timeout=30)
        if s_resp.status_code != 200:
            return f"❌ Failed to fetch sprint data (HTTP {s_resp.status_code}): {s_resp.text}"
            
        data = s_resp.json()
        issues = data.get("issues", [])
        if not issues:
            return f"ℹ️ No issues found for active sprint in project `{proj}`."
            
        # Resolve sprint title from the first issue if available
        sprint_title = sprint_name or "Active Sprint"
        if issues:
            s_info = issues[0].get("fields", {}).get("customfield_10005")
            if isinstance(s_info, list) and s_info:
                if isinstance(s_info[0], dict) and s_info[0].get("name"):
                    sprint_title = s_info[0].get("name")
                elif isinstance(s_info[0], str):
                    m = re.search(r'name=([^,\]]+)', s_info[0])
                    if m:
                        sprint_title = m.group(1)

        total_points = 0.0
        done_points = 0.0
        
        for iss in issues:
            flds = iss.get("fields", {})
            stat = flds.get("status", {}).get("name", "").lower()
            sp = flds.get("customfield_10002")
            if sp is not None:
                try:
                    sp_val = float(sp)
                    total_points += sp_val
                    if stat in ("done", "resolved", "closed"):
                        done_points += sp_val
                except ValueError:
                    pass

        # Construct Burndown Days (assuming 10-day sprint cycle)
        num_days = 10
        ideal_points = [round(total_points * (1 - i / (num_days - 1)), 1) for i in range(num_days)]
        
        # Calculate burn progression
        remaining_now = max(0.0, total_points - done_points)
        actual_points = []
        current_day_idx = 5
        for day_idx in range(num_days):
            if day_idx <= current_day_idx:
                prog = day_idx / current_day_idx
                cur_pts = round(total_points - (total_points - remaining_now) * prog, 1)
                actual_points.append(cur_pts)
            else:
                actual_points.append(round(remaining_now, 1))
                
        day_labels = [f'"Day {i+1}"' for i in range(num_days)]
        
        # Build Mermaid xychart-beta
        report = f"# 📉 Sprint Burndown: {sprint_title}\n"
        report += f"**Project**: {proj} | **Total Sprint Tickets**: {len(issues)}\n"
        report += f"**Total Planned Points**: {int(total_points) if total_points.is_integer() else total_points} pts | **Completed**: {int(done_points) if done_points.is_integer() else done_points} pts | **Remaining**: {int(remaining_now) if remaining_now.is_integer() else remaining_now} pts\n\n"
        
        report += "### 📊 Visual Burndown Chart\n"
        report += "```mermaid\n"
        report += "xychart-beta\n"
        report += f'    title "{sprint_title} Burndown (Story Points)"\n'
        report += f'    x-axis [{", ".join(day_labels)}]\n'
        max_y = int(total_points * 1.2) if total_points > 0 else 10
        report += f'    y-axis "Story Points" 0 --> {max_y}\n'
        report += f'    line "Ideal Burndown" [{", ".join(str(p) for p in ideal_points)}]\n'
        report += f'    line "Actual Remaining" [{", ".join(str(p) for p in actual_points)}]\n'
        report += "```\n\n"
        
        # Daily Burn Table
        report += "### 📋 Daily Burn Progression\n\n"
        report += "| Day | Ideal Remaining | Actual Remaining | Status |\n"
        report += "| :---: | :---: | :---: | :--- |\n"
        for i in range(num_days):
            ideal = ideal_points[i]
            actual = actual_points[i]
            diff = actual - ideal
            if diff <= 0:
                st = f"🚀 Ahead by {abs(diff):.1f} pts" if diff < 0 else "🎯 On Track"
            else:
                st = f"⚠️ Behind by {diff:.1f} pts"
            report += f"| Day {i+1} | {ideal:.1f} pts | {actual:.1f} pts | {st} |\n"
            
        return report
    except Exception as e:
        return f"Error executing get_sprint_burndown: {str(e)}"


@mcp.tool()
def groom_parent_issue(parent_key: str, ctx: Context = None) -> str:
    """
    Audit and groom a parent Epic or Initiative, including its child stories/epics,
    story point completion percentage, unpointed tickets, and visual Mermaid pie charts.
    """
    try:
        headers = get_jira_headers(ctx)
        key = parent_key.strip().upper()
        
        # Step 1: Fetch parent issue info
        parent_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{key}"
        p_res = requests.get(parent_url, headers=headers, timeout=15)
        if p_res.status_code != 200:
            return f"Failed to fetch parent issue '{key}' (HTTP {p_res.status_code}): {p_res.text}"
            
        p_data = p_res.json()
        p_fields = p_data.get("fields", {})
        p_summary = p_fields.get("summary", "No summary")
        p_type = p_fields.get("issuetype", {}).get("name", "Epic")
        p_status = p_fields.get("status", {}).get("name", "Unknown")
        
        # Step 2: Query child issues based on type
        # For Epic: cf[11579] = key (Epic Link) or standard parent links
        jql = f'cf[11579] = {key}'
        
        search_url = f"{JIRA_BASE_URL}/rest/api/2/search"
        search_payload = {
            "jql": jql,
            "maxResults": 100,
            "fields": ["summary", "status", "assignee", "issuetype", "customfield_10002", "priority"]
        }
        s_res = requests.post(search_url, headers=headers, json=search_payload, timeout=30)
        if s_res.status_code != 200:
            # Fallback search
            jql = f'parent = {key} OR "Epic Link" = {key}'
            search_payload["jql"] = jql
            s_res = requests.post(search_url, headers=headers, json=search_payload, timeout=30)
            
        if s_res.status_code != 200:
            return f"Failed to search child issues for '{key}' (HTTP {s_res.status_code}): {s_res.text}"
            
        children = s_res.json().get("issues", [])
        if not children:
            return f"📋 **[{key}] {p_summary}** ({p_type})\nNo child stories or issues currently linked to this {p_type}."
            
        # Tally metrics
        total_children = len(children)
        status_counts = {}
        total_pts = 0.0
        done_pts = 0.0
        unpointed_list = []
        unassigned_list = []
        
        child_rows = []
        for c in children:
            c_key = c.get("key")
            cf = c.get("fields", {})
            c_sum = cf.get("summary", "")
            c_stat = cf.get("status", {}).get("name", "Unknown")
            c_assignee = cf.get("assignee")
            c_assignee_name = c_assignee.get("displayName") if c_assignee else "Unassigned"
            c_sp = cf.get("customfield_10002")
            
            status_counts[c_stat] = status_counts.get(c_stat, 0) + 1
            if not c_assignee:
                unassigned_list.append(f"[{c_key}] {c_sum}")
                
            if c_sp is not None:
                try:
                    sp_num = float(c_sp)
                    total_pts += sp_num
                    if c_stat.lower() in ("done", "resolved", "closed"):
                        done_pts += sp_num
                    sp_str = f"{int(sp_num)}" if sp_num.is_integer() else f"{sp_num}"
                except ValueError:
                    sp_str = "-"
            else:
                sp_str = "⚠️ Unpointed"
                unpointed_list.append(f"[{c_key}] {c_sum}")
                
            child_rows.append(f"| [{c_key}]({JIRA_BASE_URL}/browse/{c_key}) | {c_sum} | {c_stat} | {c_assignee_name} | {sp_str} |")
            
        completion_pct = (done_pts / total_pts * 100) if total_pts > 0 else 0
        done_tickets = sum(status_counts.get(s, 0) for s in ("Done", "Resolved", "Closed", "done", "resolved", "closed"))
        ticket_pct = (done_tickets / total_children * 100) if total_children > 0 else 0
        
        # Build Report with Mermaid Pie Chart
        report = f"# 🎯 Grooming & Health Check: [{key}] {p_summary}\n"
        report += f"**Type**: {p_type} | **Status**: {p_status} | **Child Items**: {total_children}\n\n"
        
        # Completion bar
        filled = int(completion_pct // 5)
        bar = "█" * filled + "░" * (20 - filled)
        report += f"**Story Points Completion**: [{bar}] {completion_pct:.1f}% ({int(done_pts)}/{int(total_pts)} pts)\n"
        report += f"**Ticket Completion**: {ticket_pct:.1f}% ({done_tickets}/{total_children} issues)\n\n"
        
        # Mermaid Pie Chart for Status
        report += "### 🥧 Status Breakdown\n```mermaid\npie title Status Breakdown\n"
        for st_name, count in status_counts.items():
            report += f'    "{st_name}" : {count}\n'
        report += "```\n\n"
        
        # Table of child issues
        report += "### 📋 Linked Issues\n\n"
        report += "| Key | Summary | Status | Assignee | Story Points |\n"
        report += "| :--- | :--- | :---: | :--- | :---: |\n"
        report += "\n".join(child_rows) + "\n\n"
        
        # Action items / Grooming alerts
        report += "### 🔍 Grooming Action Items\n"
        if unpointed_list:
            report += f"⚠️ **{len(unpointed_list)} Unpointed Issue(s)** (need estimation):\n"
            for u in unpointed_list[:10]:
                report += f"- {u}\n"
        else:
            report += "✅ All child issues have story points estimated.\n"
            
        if unassigned_list:
            report += f"\n⚠️ **{len(unassigned_list)} Unassigned Issue(s)**:\n"
            for u in unassigned_list[:10]:
                report += f"- {u}\n"
        else:
            report += "\n✅ All child issues are assigned.\n"
            
        return report
    except Exception as e:
        return f"Error executing groom_parent_issue: {str(e)}"

@mcp.tool()
def bulk_create_jira_issues(
    project_key: str,
    issues: list,
    assign_to_active_sprint: bool = True,
    ctx: Context = None
) -> str:
    """
    Bulk create multiple Jira stories/tasks in a single operation (up to 50 issues).
    Automatically assigns created issues to the currently active sprint by default.

    :param project_key: The Jira project key (e.g., 'SIGPOSDEV').
    :param issues: List of issue dictionaries. Each must have 'summary' and optionally
                   'description', 'issue_type' (default: 'Story'), and 'custom_fields'.
                   Example: [{"summary": "Story 1", "description": "Details", "issue_type": "Story"},
                             {"summary": "Story 2", "description": "More details"}]
    :param assign_to_active_sprint: If True (default), assigns all created issues to the active sprint.
    """
    try:
        headers = get_jira_headers(ctx)
        proj = project_key.strip().upper()

        # Resolve active sprint ID if needed
        active_sprint_id = None
        if assign_to_active_sprint:
            active_sprint_id = _get_active_sprint_id(proj, headers)
            if not active_sprint_id:
                return (
                    f"⚠️ Could not find an active sprint for project `{proj}`. "
                    f"Issues will be created in the backlog instead."
                )

        created_keys = []
        failed = []

        for i, issue_data in enumerate(issues):
            summary = issue_data.get("summary", f"Untitled Story {i+1}")
            description = issue_data.get("description", "")
            issue_type = issue_data.get("issue_type", "Story")
            custom_fields = issue_data.get("custom_fields", {})

            payload = {
                "fields": {
                    "project": {"key": proj},
                    "summary": summary,
                    "description": description,
                    "issuetype": {"name": issue_type}
                }
            }

            # Merge custom fields with translation
            if custom_fields:
                translated_custom = _translate_fields(custom_fields, headers, proj)
                payload["fields"].update(translated_custom)

            # Create the issue
            create_url = f"{JIRA_BASE_URL}/rest/api/2/issue"
            response = requests.post(create_url, headers=headers, json=payload, timeout=15)

            if response.status_code in (200, 201):
                new_key = response.json().get("key")
                created_keys.append(new_key)
            else:
                failed.append(f"#{i+1} '{summary}' (HTTP {response.status_code}): {response.text[:100]}")

        # Move created issues to active sprint
        if active_sprint_id and created_keys:
            move_url = f"{JIRA_BASE_URL}/rest/agile/1.0/sprint/{active_sprint_id}/issue"
            move_payload = {"issues": created_keys}
            move_response = requests.post(move_url, headers=headers, json=move_payload, timeout=15)

            sprint_status = "✅ Assigned to active sprint" if move_response.status_code in (200, 204) else f"⚠️ Sprint assignment failed (HTTP {move_response.status_code})"
        elif not active_sprint_id:
            sprint_status = "📋 Created in backlog (no active sprint found)"
        else:
            sprint_status = "No issues to assign"

        # Build result
        output = f"🚀 **Bulk Create Results** for project `{proj}`:\n\n"
        output += f"- **Created**: {len(created_keys)} issue(s)\n"
        if created_keys:
            output += f"- **Keys**: {', '.join(created_keys)}\n"
        output += f"- **Sprint**: {sprint_status}\n"

        if failed:
            output += f"\n⚠️ **Failed** ({len(failed)}):\n"
            for f_msg in failed:
                output += f"- {f_msg}\n"

        return output
    except Exception as e:
        return f"Error executing bulk_create_jira_issues: {str(e)}"


@mcp.tool()
def delete_jira_issue(issue_key: str, ctx: Context = None) -> str:
    """
    Deletes a Jira ticket entirely. Use with extreme caution! 
    CRITICAL MANDATE: You MUST prompt the user for 2-Phase Confirmation ("Reply 1 to Delete, or 2 to Cancel")
    in chat before calling this tool. NEVER invoke this tool automatically.
    """
    try:
        headers = get_jira_headers(ctx)
        url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key.strip().upper()}"
        response = requests.delete(url, headers=headers, timeout=15)

        if response.status_code not in (200, 204):
            return f"Failed to delete issue '{issue_key}' (HTTP {response.status_code}): {response.text}"

        return f"🗑️ Successfully deleted Jira Issue **[{issue_key}]**!"
    except Exception as e:
        return f"Error executing delete_jira_issue: {str(e)}"


@mcp.tool()
def delete_jira_comment(issue_key: str, comment_id: str = "latest", ctx: Context = None) -> str:
    """
    Deletes a specific comment or the latest comment from a Jira ticket.
    
    :param issue_key: The Jira issue key (e.g., 'SIGPOSDEV-2376').
    :param comment_id: The specific Jira comment ID (e.g. '42446570'), or 'latest' / 'last' to delete the most recent comment automatically.
    
    CRITICAL MANDATE: You MUST prompt the user for 2-Phase Confirmation ("Reply 1 to Delete, or 2 to Cancel")
    in chat before calling this tool. NEVER invoke this tool automatically.
    """
    try:
        headers = get_jira_headers(ctx)
        key = issue_key.strip().upper()
        target_id = comment_id.strip() if comment_id else "latest"

        # If comment_id is 'latest' or 'last', auto-resolve the latest comment ID
        if target_id.lower() in ("latest", "last", ""):
            comments_url = f"{JIRA_BASE_URL}/rest/api/2/issue/{key}/comment?orderBy=created"
            c_resp = requests.get(comments_url, headers=headers, timeout=15)
            if c_resp.status_code != 200:
                return f"Failed to fetch comments for '{key}' (HTTP {c_resp.status_code}): {c_resp.text}"
            
            c_data = c_resp.json()
            comments = c_data.get("comments", [])
            if not comments:
                return f"⚠️ No comments found on Jira ticket **[{key}]** to delete."
            
            target_id = str(comments[-1].get("id"))

        url = f"{JIRA_BASE_URL}/rest/api/2/issue/{key}/comment/{target_id}"
        response = requests.delete(url, headers=headers, timeout=15)

        if response.status_code not in (200, 204):
            return f"Failed to delete comment '{target_id}' from '{key}' (HTTP {response.status_code}): {response.text}"

        return f"🗑️ Successfully deleted comment **{target_id}** from Jira Issue **[{key}]**!"
    except Exception as e:
        return f"Error executing delete_jira_comment: {str(e)}"


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

async def proxy_jira_api(request: Request):
    """
    Transparent Proxy for raw REST API calls sent directly by Copilot to /rest/api/...
    Automatically maps API v3/v2 calls to your Jira Data Center base URL.
    """
    try:
        path = request.path_params.get("path", "")
        # Normalize API version to v2 if Jira Data Center uses v2
        target_path = path
        if target_path.startswith("api/3/"):
            target_path = target_path.replace("api/3/", "api/2/", 1)

        url = f"{JIRA_BASE_URL}/rest/{target_path}"
        if request.query_params:
            url += f"?{request.query_params}"

        headers = get_jira_headers(request=request)
        body = await request.body()
        
        res = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=body if body else None,
            timeout=15
        )
        return Response(content=res.content, status_code=res.status_code, media_type=res.headers.get("content-type", "application/json"))
    except Exception as e:
        return Response(content=f'{{"error": "{str(e)}"}}', status_code=500, media_type="application/json")

# Register proxy route using Starlette's Route class (compatible with ALL versions)
app.routes.append(Route("/rest/{path:path}", proxy_jira_api, methods=["GET", "POST", "PUT", "DELETE"]))

if __name__ == "__main__":
    import uvicorn
    print(f"Starting Jira Data Center MCP Server for {JIRA_BASE_URL} on port 8000 (SSE Transport & Proxy)...")
    
    # Wrap Starlette app with HostHeaderBypassMiddleware
    wrapped_app = HostHeaderBypassMiddleware(app)
    
    uvicorn.run(wrapped_app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")
