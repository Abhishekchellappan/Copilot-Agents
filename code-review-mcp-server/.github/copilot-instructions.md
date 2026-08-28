# GitHub Copilot Instructions - Code Review Agent

These instructions define the interactive workflow rules for Copilot when working
with the Code Review Agent (`@code-review-agent`) for local workspace reviews
and Gerrit permalink reviews (`wall.lge.com`).

---

## 📜 Code Review Guidelines Enforced

The agent automatically enforces rules from:
1. **ISO C++ Core Guidelines** (Smart pointers `std::unique_ptr`, `override` keyword, `const T&` passing, no raw `new`/`delete`, C++ named casts).
2. **Google C++ Style Guide** (`PascalCase` types, `snake_case_` private variables, `kPascalCase` constants, `#ifndef PROJECT_PATH_FILE_H_` guards).
3. **HS Collaboration Center API Design & Development Rules** (RESTful plural endpoints, URL versioning `/v1/`, standard JSON error response schema, Luna Bus `lowerCamelCase` LS2 methods, `.role.json` / `.perm.json` security manifests).
4. **Security & Vulnerability Standards** (No hardcoded secrets/IPs, no C-style array overflows).
5. **LG / webOS Platform Rules** (`ACP_SPECIFIC`, platform linking, `lib32-` multilib, copyright year).
6. **Dart & Flutter Best Practices** (Effective Dart, `const` widgets, mandatory controller/stream disposal in `dispose()`, `if (!mounted)` before `setState()`, unsafe `late` and `!` checks, `cacheWidth`/`cacheHeight` image optimizations).

---

## 🔍 Code Review Workflow

### Scenario A: Local Workspace Code Review
When the user asks to review code in the current workspace (open file, git diff, or pasted code):
1. Read the file content or code snippet.
2. Use `@code-review-agent` to call `review_local_code` with the code text and filename.
3. Display the formatted line-by-line review comments directly in the **VS Code Chat Window**.
4. Do NOT post to Gerrit for local reviews.

### Scenario B: Gerrit Permalink / Change ID Review (`wall.lge.com`)
When the user provides a Gerrit permalink URL or Change ID number:

> ⚠️ **CRITICAL TOOL SELECTION RULE**: You MUST strictly invoke the `analyze_gerrit_change` tool to perform the review. 
> 🚫 **NEVER USE** the `get_gerrit_comments` tool for an initial review! (`get_gerrit_comments` is ONLY for checking status *after* posting).
> 🚫 **NEVER search local workspace files** on disk during a Gerrit review. Perform the code review EXCLUSIVELY on the diff text returned by `analyze_gerrit_change`.
> 🚫 **NEVER ask the user to authenticate or set up SSH keys**. Gerrit HTTP authentication is ALREADY handled automatically by the MCP server (`X-Gerrit-User`/`X-Gerrit-Pass` headers). You MUST directly invoke `post_gerrit_review_comments` when requested!
> 🚫 **NEVER hallucinate** or assume comments were posted. You MUST follow the 3 phases below exactly.

#### Phase 1: Fetch Diffs & Perform AI Review (Automatic)
1. Extract the Change ID from the URL or number.
2. Call `analyze_gerrit_change` with the Change ID to fetch raw modified code diffs and comment threads from Gerrit.
3. **PERFORM THE AI REVIEW YOURSELF**: Immediately read `CODE_REVIEW_RULES.md` in the workspace root and analyze the returned code diff lines against all guidelines (ISO C++, Google Style, Smart Pointers, Const correctness, HS API Rules, Security).
4. **DEFECT-ONLY RULE**: ONLY generate inline comments for **actual issues, bugs, security flaws, performance concerns, or rule violations**. Do NOT generate inline comments to praise or compliment correct code lines. If a line is correct, do NOT create a comment for it.
5. Display the comprehensive code review report in VS Code chat (MUST include Change ID, Subject, Project, Owner, Files Changed, Thread Status, Issues Table, and Voting Recommendation).

#### Phase 2: Interactive Destination Choice ⚠️ (MANDATORY PAUSE)
**STOP** after analysis and present the user with exactly these options:

> "🔍 AI Code Review completed for Gerrit Change **<change-id>**! Found **X** review comment(s).
>
> Where would you like to post these review comments?
> 1️⃣ 🌐 **Post directly to Gerrit** (inline unresolved comments with AI signature)
> 2️⃣ 💬 **Keep in VS Code Chat Window** (already displayed above)
>
> Please reply with **1** or **2**."

**Do NOT post any comments to Gerrit until the user explicitly selects Option 1.**

#### Phase 3: Execute User Choice
- **If user selects 1 (Post to Gerrit)**:
  - You MUST use `@code-review-agent` to call the tool `post_gerrit_review_comments`.
  - Pass the `change_id` argument (e.g. `change_id="770233"`).
  - Pass your generated review findings using the `review_comments` argument as a structured JSON dict. Example format:
    ```json
    {
      "src/main.cpp": [{"line": 45, "message": "Fix this memory leak"}],
      "src/utils.cpp": [{"line": 12, "message": "Add const to parameter"}]
    }
    ```
  - Do NOT pass raw markdown text. You must format the issues into the `review_comments` dictionary exactly.
  - Do NOT include severity/category prefixes like `⚠️ **Code Quality**:` or `**Maintainability**:` in the message string. Plain comment text only.
  - Do NOT hallucinate apologies; you must execute the tool call!

- **If user selects 2 (Keep in Chat)**:
  - Do nothing further. The review comments are already displayed in the chat window.
  - Inform the user: "Review comments are displayed above. No comments were posted to Gerrit."

---

## 📋 Review Comment Format

### In VS Code Chat Window:
Display review comments as a formatted table with:
- Line number
- Severity (Critical / Error / Warning / Info)
- Category (Security / Code Quality / Legal / C++ Core / Google Style / API Design)
- Issue description
- Code snippet showing the problematic line

### In Gerrit (Inline Comments):
Each inline comment posted to Gerrit must:
- Be attached to the specific **file** and **line number**.
- Be marked as **unresolved** (`"unresolved": true`).
- Contain **plain description text only** — do NOT include prefixes like `⚠️ **Code Quality**:` or `**Maintainability**:`.
- Do NOT add a signature in Copilot prompt; the server automatically appends the single signature footer `*Posted by LGSI Gpos AI Agent*`.

---

## 📋 General Rules

1. **Never post to Gerrit without user confirmation** in Phase 2.
2. **Always display analysis results in chat first** before asking where to post.
3. **Apply all active CODE_REVIEW_RULES.md rules** (C++ Core Guidelines, Google C++ Style, HS API Rules).
4. **DEFECT-ONLY INLINE COMMENTS**: Only create inline comments for actionable issues, bugs, or rule violations. Never post inline comments complimenting correct code.
5. **DO NOT SEARCH LOCAL DISK**: For Gerrit reviews, analyze ONLY the diff text returned by `analyze_gerrit_change`. Never attempt to search local workspace folders for Gerrit files.
6. **AUTOMATIC GERRIT AUTH**: Never ask the user to set up SSH keys or Git credentials. Authentication is handled automatically via HTTP Basic Auth in `mcp.json`. Always call `post_gerrit_review_comments` directly.
7. **For local workspace reviews**, always output to VS Code Chat Window (never Gerrit).
8. **For Gerrit reviews**, always pause and ask the user for destination choice.
