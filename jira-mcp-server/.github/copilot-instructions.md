# GitHub Copilot Instructions for Jira Ticket Management & Auto-Labeling

This guide defines the automatic labeling rules, workflow mappings, and standards for GitHub Copilot when interacting with Jira via the `@jira-data-center` MCP server.

---

## 🏷️ Automatic Labeling Rules by Phase & Workflow

When creating, updating, or auditing Jira stories, analyze the title, description, and task context, then **automatically assign the corresponding labels**:

### 1. Requirements & Analysis Phase
* **Label**: `AX_REQ`
* **Applicable Workflows / Use Cases**:
  - Going through requirements / SRS / RFC documents
  - Defining functional and non-functional requirements
  - Reviewing feasibility of implementation
  - Scope estimation (effort, timeline, complexity)
* **Status / Output Label**: Add `Analysis_done` when research, exploration, or feasibility analysis is complete.

---

### 2. High-Level Design (HLD) Phase
* **Label**: `AX_HLD`
* **Applicable Workflows / Use Cases**:
  - Defining system context, boundaries, and architecture
  - Static design & Class diagrams
  - Dynamic design & Sequence diagrams
  - Designing data flow & message formats
  - High-Level Design (HLD) reviews & sign-offs

---

### 3. Detailed Software Design (SDS) Phase
* **Label**: `AX_SDS`
* **Applicable Workflows / Use Cases**:
  - Designing module internals (classes, methods, state machines)
  - Defining API interfaces, logic flows, and data structures
  - Detailed Software Design (SDS) reviews

---

### 4. Software Implementation Phase
* **Label**: `AX_IMPL`
* **Applicable Workflows / Use Cases**:
  - Implementing module code (classes, methods, logic) with AI assistance
  - Writing unit tests, integration tests, and test mocks
  - Running static analysis (linting, security scans, SonarQube)
  - Local build and artifact packaging
  - Peer code review and pull request feedback
  - Fixing review comments & bug fixes
  - Code maintenance and stabilization
* **Status / Output Label**: Add `code_merged` when code implementation, PR review, and merging are complete.

---

## 📊 Summary Table of AX Phase Labels

| Task / Phase | AX Label | Trigger Keywords / Workflows | Additional Label |
| :--- | :--- | :--- | :--- |
| **Requirements Analysis & Refinement** | `AX_REQ` | Requirements, Scope, Feasibility, Exploration, Specification | `Analysis_done` |
| **High-Level Design (SDS)** | `AX_HLD` | System Context, Architecture, Class Diagram, Sequence Diagram, Data Flow | — |
| **SW Detailed Design (SDS)** | `AX_SDS` | Module Internals, Interfaces, Logic Flow, Detailed Design | — |
| **SW Implementation** | `AX_IMPL` | Coding, Unit Tests, Mocks, Linting, Build, PR Review, Bug Fixing | `code_merged` |

---

## 🏷️ Context-Based Labeling Rules (New)

In addition to the AX phase labels above, analyze the story title, description, and context to **automatically apply the following labels**:

| Category / Context | Label | Trigger Keywords / Conditions |
| :--- | :--- | :--- |
| **Training & Skill Up** | `training` | SWPCT, LSET, Skill Up, training, certification, exam, practising, learning |
| **Implementation / Development** | `development` | Coding, implementation, feature development, bug fix, integration, deploy, build |
| **Exploration / Research (No Dev)** | `Analysis-Done` | Exploration, research, investigation, feasibility study — with NO implementation/coding work |
| **Operations & Ceremonies** | `operations` | Sprint grooming, sprint planning, retrospective, team sync, standup, backlog refinement |
| **Unplanned Leave** | `unplanned_leave` | Unplanned leave, sick leave, emergency leave |

> **Multi-Labeling**: A story can have BOTH an AX phase label (e.g. `AX_IMPL`) AND a context label (e.g. `development`). Apply all that match.

> **⚠️ STRICT LABEL WHITELIST**: You MUST ONLY use labels from the predefined lists above. The ONLY valid labels are: `AX_REQ`, `AX_HLD`, `AX_SDS`, `AX_IMPL`, `Analysis_done`, `code_merged`, `training`, `development`, `Analysis-Done`, `operations`, `unplanned_leave`. **NEVER invent, create, or hallucinate new label names** (e.g. do NOT use `education`, `learning`, `skill-up`, or any label not in this list).

---

## 🧩 Component Auto-Assignment Rules

When creating or updating Jira stories, automatically assign the correct **Component** based on the story context:

| Story Type / Context | Component Name | Trigger Keywords |
| :--- | :--- | :--- |
| **LSET / Skill Up / SWPCT / Training** | `2026_HS_GPOS_Platform_SkillUp` | LSET, SWPCT, Skill Up, training, certification, exam |
| **Planned Leave** | `2026_HS_Planned_Leave` | Planned leave, vacation, PTO, holiday |
| **Unplanned Leave** | `2026_HS_Unplanned_Leave` | Unplanned leave, sick leave, emergency leave |
| **Default (All Other Stories)** | `2026_HS_GPOS_PLATFORM` | Fallback when no specific component matches or the relevant module/component is not available |

> **IMPORTANT**: If the user explicitly specifies a component, use that instead of the auto-assigned one. The rules above are defaults for when no component is provided.

---

---

## 💬 Standard Jira Comment Formatting Structure & Styling Rules

Whenever you are asked to add a comment summarizing task progress or work completed, the comment **MUST strictly follow this clean layout without any leading numbers like "1." or "1. 1."**:

### 📌 Work Summary
A 1-2 sentence overview of the task/work done.

**AI Contribution**:
- Bullet points detailing what you (the AI) generated, analyzed, refactored, or assisted with.

**Developer Contribution**:
- Bullet points detailing what the developer reviewed, implemented, tested, or configured.

> **⚠️ DO NOT USE NUMBERED LISTS FOR HEADINGS**: Never start section titles with numbers (e.g. do NOT write `1. Work Summary` or `1. 1. Work Summary`). Always use clean markdown headings (`### 📌 Work Summary`) or bold text (`**AI Contribution**:`).

### 🔍 Context-Aware Comment Generation Rule
When asked to add a comment to a ticket (e.g., "add a meaningful comment to SIGPOSDEV-2376"):
1. If the user did NOT provide explicit comment text, you **MUST FIRST call `get_jira_issue` or `get_jira_comments`** to read the ticket's summary, description, and status.
2. Synthesize a **ticket-specific, meaningful comment** based on that actual ticket context. NEVER use generic placeholder text like "Created and configured Jira story...".

### 🎨 Styling Constraints
* **Bold Titles & Headings**: Titles and section headers MUST use bold font or Markdown headings (e.g. `### 📌 Work Summary` or `**AI Contribution**:`).
* **Code Blocks**: Any code snippet, shell command, config snippet, or JSON payload MUST be formatted inside fenced Markdown code blocks with language identifiers (e.g., ````cpp````, ````dart````, ````json````, ````bash````).
* **Tables**: Comparative data, audit logs, or test result metrics MUST be formatted as standard Markdown tables (`| Column 1 | Column 2 |`).

#### Example Clean Structured Layout:
```markdown
### 📌 Work Summary
Implemented user authentication API endpoints and added unit tests for token validation.

**AI Contribution**:
- Generated initial OpenAPI schema definitions and boilerplate request/response handlers.
- Drafted unit test cases covering edge cases (token expiration, invalid signatures).

**Developer Contribution**:
- Reviewed and integrated the handlers into the main service controller.
- Configured JWT secrets and ran integration tests against the local database.
```

---

## 🛡️ Safety Controls & 2-Phase Confirmation Protocol (STRICT ENFORCEMENT)

**🛑 CRITICAL MANDATORY RULE:** Agent actions that modify or delete Jira data (`add_jira_comment`, `update_jira_issue`, `delete_jira_issue`, `delete_jira_comment`) **MUST NEVER BE EXECUTED AUTOMATICALLY IN YOUR FIRST RESPONSE**.

You are **STRICTLY FORBIDDEN** from calling mutating tools on your first turn. Your FIRST response MUST ONLY display the draft action and ask for confirmation:

1. **Adding a Comment:** 
   - Step 1: Call `get_jira_issue` or `get_jira_comments` to read ticket context (if needed).
   - Step 2: Draft the comment following the clean layout above.
   - Step 3: Show the draft comment text to the user in chat.
   - Step 4: **STOP and ask**: *"Reply 1 to Post, or 2 to Cancel."*
   - Step 5: **DO NOT call `add_jira_comment`** until the user explicitly replies with `1` or positive confirmation.

2. **Deleting a Ticket:** Display the target ticket key and summary. Ask: *"Reply 1 to Delete, or 2 to Cancel."* Do NOT call `delete_jira_issue` until confirmed.
3. **Deleting a Comment:** When asked to delete a comment (e.g. "delete comment" or "delete the last comment"), **NEVER ask the user for the comment ID**. Automatically resolve it using `get_jira_comments` or by passing `comment_id='latest'`. Display the comment text/snippet and target ticket key in chat, then ask: *"Reply 1 to Delete, or 2 to Cancel."* Do NOT call `delete_jira_comment` until confirmed.
4. **Updating Ticket Fields:** Display modified fields and target ticket key. Ask: *"Reply 1 to Update, or 2 to Cancel."* Do NOT call `update_jira_issue` until confirmed.

You MUST NOT execute the tool until the user replies with `1` (or equivalent positive confirmation) in the chat.

---

## 🛠️ Custom Fields Initialization & Aliases

When creating new Jira issues via `create_jira_issue`:
1. **`AX_phase` and `AX_Save`** are automatically set to `"0"` by default on backend. **CRITICAL: When creating a NEW Story, you MUST NOT override these with AX_IMPL or any other value. Always let them default to "0".**
2. The issue will be automatically assigned to the active sprint unless specified otherwise.
3. The default **Component** is `2026_HS_GPOS_PLATFORM` unless a specific component is matched by the Component Auto-Assignment Rules above.
4. You can use user-friendly field aliases instead of internal IDs (e.g., `sprint`, `epic_link`, `ax_phase`, `ax_save`, `story_points`, `component`) in the `custom_fields` or `fields` dictionaries for both `create_jira_issue` and `update_jira_issue`.
5. **New Field Aliases**: The following additional fields are now supported:
   - `original_story_points` → `customfield_20403` (Original Story Points)
   - `start_date` / `start_date_alm` → `customfield_23191` (Start Date_ALM, format: `YYYY-MM-DD`)
   - `watchers_alm` → `customfield_23192` (Watchers._ALM multi-user picker)
   - `due_date` → `duedate` (standard Jira field, format: `YYYY-MM-DD`)
   - `fix_version` / `fix_versions` → `fixVersions` (auto-wrapped to `[{"name": "..."}]`)
   - `original_estimate` → `timetracking.originalEstimate` (e.g., `"2d"`, `"4h"`)
   - `time_spent` → `timespent` (read-only, use work log API to add)
   - `resolution` → `resolution` (auto-wrapped to `{"name": "..."}`, e.g., `"Done"`, `"Won't Fix"`)

---

## 📋 General Rules for Copilot Chat

1. **Default Project Key**: Always default to **`SIGPOSDEV`** if the user doesn't specify a project key. Never ask the user which project key to search in or guess iteratively; use `SIGPOSDEV` automatically.
2. **Table Output Format**: Whenever listing issues, searching sprint tickets, or summarizing stories, ALWAYS present them as a clean, structured **Markdown Table** with the following columns:
   `| Key | Summary | Status | Assignee | Priority | Link |`
3. **Sprint Enforcement**: If the user provides a specific sprint name (e.g., `2026_GPOS1SP18(8/31-09/11)`), pass that EXACT string to the `sprint` custom field. ONLY fallback to `"active"` if the user does NOT specify a sprint.
4. **Multi-Labeling**: Apply both the phase label (e.g., `AX_IMPL`) and context label (e.g., `development`, `training`) when both apply.
5. **Context-Aware Comment Replies**: When asked to reply to a ticket comment, read the full chronological comment thread + Title + Description + DOD to synthesize a polite, contextually accurate response.

---

## 🚨 Mandatory Field Processing Checklist (Issue Creation)

When the user requests creating a Jira issue and provides multiple fields, you MUST process **ALL** of the following fields if mentioned by the user. Do NOT skip or drop any field:

| User Field | Tool Parameter |
| :--- | :--- |
| Summary | `summary` |
| Description | `description` (see Description Generation Rule below) |
| Assignee | `assignee: "username"` |
| Story Points | `story_points: <number>` |
| Original Story Points | `custom_fields: {"original_story_points": <number>}` |
| Labels | `labels: ["label1", "label2"]` (If user says "add respective labels", evaluate context and generate relevant labels e.g. `["AX_REQ", "development"]`. Do NOT drop the field.) |
| Priority | `custom_fields: {"priority": {"name": "P2"}}` |
| Sprint | `sprint: "2026_GPOS1SP18(8/31-09/11)"` (Use user's string if provided, else `"active"`) |
| Component | `custom_fields: {"component": "ComponentName"}` |
| Epic Link | `custom_fields: {"epic_link": "SIGPOSDEV-XXXX"}` |
| Fix Version/s | `custom_fields: {"fix_version": "v1.0"}` or `{"fix_versions": ["v1.0", "v2.0"]}` |
| Start Date | `custom_fields: {"start_date": "2026-08-10"}` |
| Due Date | `custom_fields: {"due_date": "2026-08-15"}` |
| Original Estimate | `custom_fields: {"original_estimate": "2d"}` |
| Resolution | `custom_fields: {"resolution": "Done"}` |

> **⚠️ CRITICAL**: Before calling `create_jira_issue`, cross-check your tool call arguments against the user's request. Every field the user mentioned MUST be present in your tool call. If you missed a field, add it before executing.

---

## ✍️ Description Generation Rule

When the user asks for a "meaningful description" or says "add a description based on the summary":
- You MUST generate a **detailed, expanded description** (3-5 sentences minimum) that explains the purpose, scope, and expected outcome of the story.
- You MUST NOT simply copy or repeat the summary text as the description.
- Include: What needs to be done, why it matters, and what the expected deliverable or outcome is.

**Example:**
- Summary: `SWPCT training`
- ❌ BAD Description: `SWPCT training`
- ✅ GOOD Description: `Complete the SWPCT (Software Process Compliance Training) certification exam as part of the ongoing skill development initiative. This includes studying the required modules, practicing with sample questions, and passing the final assessment to ensure compliance with organizational software process standards.`

---

## 🔍 Sprint Audit Guidelines (`audit_sprint_issues`)

When the user asks to "audit the sprint", "audit labels", or "check missing items in sprint":
1. Call `audit_sprint_issues(project_key='SIGPOSDEV')`.
2. **NEVER invent or pass non-existent labels** like `AX-Approved` or `Reviewed`.
3. The tool checks for:
   - **Valid Category / AX Labels**: `training`, `development`, `operations`, `Analysis-Done`, `unplanned_leave`, `AX_REQ`, `AX_HLD`, `AX_SDS`, `AX_IMPL`.
   - **Assignee**: Flags unassigned tickets.
   - **Story Points**: Checks `customfield_10002`.
4. Output the audit findings as a clean Markdown table with direct links to affected tickets, and summarize which tickets need attention.

---

## 📊 Sprint Report Guidelines (`generate_sprint_report`)

When the user asks for a "sprint report", "sprint health", "sprint status", "sprint summary", or "developer workload breakdown":
1. Call `generate_sprint_report(project_key='SIGPOSDEV')` — or with a specific `sprint_name` if requested.
2. **DO NOT manually compute story points, velocity, or completion percentages.** The `generate_sprint_report` tool does ALL calculations server-side in Python with real Jira data.
3. **Display the tool output as-is** — it is a complete, pre-formatted Markdown report. Do NOT modify, summarize, or recalculate any numbers.
4. The report includes:
   - 📈 Sprint Overview (Done / In Progress / To Do — by tickets and story points)
   - Sprint Completion Bar (percentage by points and by tickets)
   - 👥 Per-Developer Breakdown (tickets, points, done/IP/todo split per developer)
   - 📂 Issue Type Distribution (Story, Bug, Task, Sub-task counts)
   - ⚠️ At-Risk Items (unassigned, zero-point, blocked tickets)

---

## 🚫 Anti-Hallucination Rules for Story Points (`[SP XX]` Prefix)

> **⚠️ STRICT STORY POINT RULES (NEVER VIOLATE):**
> 1. In ticket summaries like `[SP 16] Deploy...` or `[SP 15] Fix...`, the prefix `[SP XX]` stands for **Sprint XX (Sprint 16, Sprint 15)** — **NOT Story Points**!
> 2. **NEVER interpret `[SP 16]` as 16 Story Points.** 
> 3. Only use the Story Points value explicitly returned by the tool (e.g. `Story Points: 2 pts` or `Story Points: Unpointed (-)`).
> 4. If a ticket has no story points assigned or says `Unpointed (-)`, display `-` or `0`. **NEVER multiply tickets by 16 or claim total story points is 160.**

---

## 🚫 Anti-Hallucination Rules for Summaries and Counting

> **⚠️ DO NOT INVENT SUMMARY STATISTICS:**
> Large Language Models (LLMs) are notoriously bad at math and counting.
> When displaying a list of Jira issues from `search_jira_issues`, **DO NOT generate a "Summary" section** (e.g., "In Progress: 5, Open: 2, Total points: 20") at the bottom of your response unless the user explicitly asks you to count them manually. 
> If the user wants an accurate sprint summary, remind them to use the `/sprint report` command or call the `generate_sprint_report` tool, which calculates exact metrics on the server side using real Jira data.

---

## 🔄 Issue Status Transitions (`transition_jira_issue`)

When the user asks to change the status of a ticket (e.g. "move to In Progress", "resolve ticket", "close ticket", "reopen SIGPOSDEV-123"):
1. **DO NOT use `update_jira_issue` for status changes.** Use `transition_jira_issue(issue_key, target_status)`.
2. **2-Phase Confirmation**: Display in chat:
   > *"I will transition **[SIGPOSDEV-XXXX]** to status **'Resolved'**. Reply **1** to Confirm, or **2** to Cancel."*
3. Only call `transition_jira_issue` after user confirmation.

---

## ⏱️ Work Logging Guidelines (`log_jira_work`)

When the user asks to log work / time on a ticket (e.g. "log 2h on SIGPOSDEV-2278", "logged 1d 4h with comment 'Finished integration'"):
1. Call `log_jira_work(issue_key, time_spent, comment)`.
2. **2-Phase Confirmation**: Display in chat:
   > *"I will log **2h** on **[SIGPOSDEV-XXXX]** with comment 'Work completed'. Reply **1** to Confirm, or **2** to Cancel."*
3. Only call `log_jira_work` after user confirmation.

---

## 🎯 Epic & Initiative Grooming (`groom_parent_issue`)

When the user asks to "groom epic", "groom initiative", "check epic health", or "audit epic stories":
1. Call `groom_parent_issue(parent_key='SIGPOSDEV-XXXX')`.
2. The tool automatically detects whether the key is an Epic or Initiative, fetches all linked child tickets, checks for unpointed tickets, and renders native **Mermaid Pie Charts** for status & story points.
3. Display the tool's pre-formatted Markdown output directly to the user.

---

## 📉 Sprint Burndown Chart (`get_sprint_burndown`)

When the user asks for a "burndown chart", "sprint burndown", "ideal vs actual burn", or "burn progress":
1. Call `get_sprint_burndown(project_key='SIGPOSDEV')`.
2. The tool calculates daily ideal vs actual remaining story points and renders an interactive **Mermaid `xychart-beta` line chart** and a daily burn progression table.
3. Display the tool's output directly to the user.


