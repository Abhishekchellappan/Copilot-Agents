import os
import re
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

# Import FastMCP with fallback support
try:
    from mcp.server.fastmcp import FastMCP, Context
except ImportError:
    try:
        from fastmcp import FastMCP, Context
    except ImportError:
        raise ImportError("Failed to import FastMCP. Please ensure 'mcp[cli]' or 'fastmcp' is installed via pip.")

# Initialize FastMCP server
mcp = FastMCP("Build Automation Agent")

# ============================================================================
# CENTRALIZED BUILD TARGET REGISTRY
# Add new targets here. All team members get updates instantly after pod restart.
# ============================================================================
BUILD_TARGETS = {
    "k26": {
        "description": "K26 Starfish HE Build",
        "repo": "ssh://wall.lge.com/starfish/build-starfish.git",
        "branch": "@webos4media",
        "mcf_target": "k26",
        "mcf_parallel": 12,
        "mcf_build_threads": 12,
        "premirror": "file:///mnt/mirrorswp/starfish_he/webos4media-downloads",
        "sstatemirror": "file:///mnt/mirrorswp/starfish_he/webos4media-sstate-cache",
        "default_image": "lib32-starfish-global-flash"
    },
    "k26apl": {
        "description": "K26 APL Starfish HE Build",
        "repo": "ssh://wall.lge.com/starfish/build-starfish.git",
        "branch": "@webos4media",
        "mcf_target": "k26apl",
        "mcf_parallel": 12,
        "mcf_build_threads": 12,
        "premirror": "file:///mnt/mirrorswp/starfish_he/webos4media-downloads",
        "sstatemirror": "file:///mnt/mirrorswp/starfish_he/webos4media-sstate-cache",
        "default_image": "lib32-starfish-global-flash"
    },
    "k26apl": {
            "description": "K26APL @spb4apl Starfish HE Build",
            "repo": "ssh://wall.lge.com/starfish/build-starfish.git",
            "branch": "@spb4apl",
            "mcf_target": "k26apl",
            "mcf_parallel": 12,
            "mcf_build_threads": 12,
            "premirror": "file:///mnt/mirrorswp/starfish_he/webos4media-downloads",
            "sstatemirror": "file:///mnt/mirrorswp/starfish_he/webos4media-sstate-cache",
            "default_image": "lib32-starfish-global-flash"
        }
}

# ============================================================================
# BITBAKE TASK REGISTRY
# Maps natural language task names to exact bitbake flags.
# ============================================================================
BITBAKE_TASKS = {
    "build":          {"flag": "",                "desc": "Full build of the recipe/image"},
    "compile":        {"flag": "-c compile",      "desc": "Run only the compile task"},
    "configure":      {"flag": "-c configure",    "desc": "Run only the configure task"},
    "clean":          {"flag": "-c clean",        "desc": "Clean build output for the recipe"},
    "cleanall":       {"flag": "-c cleanall",     "desc": "Clean build output AND fetched sources"},
    "cleansstate":    {"flag": "-c cleansstate",  "desc": "Clean shared state cache for the recipe"},
    "devshell":       {"flag": "-c devshell",     "desc": "Open interactive Yocto development shell"},
    "listtasks":      {"flag": "-c listtasks",    "desc": "List all available tasks for the recipe"},
    "fetch":          {"flag": "-c fetch",        "desc": "Fetch source code for the recipe"},
    "patch":          {"flag": "-c patch",        "desc": "Apply patches to the source"},
    "install":        {"flag": "-c install",      "desc": "Run install task for the recipe"},
    "package":        {"flag": "-c package",      "desc": "Package the compiled output"},
    "force_compile":  {"flag": "-C compile",      "desc": "Force re-compile (ignores stamps)"},
    "force_configure":{"flag": "-C configure",    "desc": "Force re-configure (ignores stamps)"},
    "env":            {"flag": "-e",              "desc": "Print bitbake environment variables"},
}

# ============================================================================
# COMMON BUILD ERROR PATTERNS
# Used by diagnose_build_log to identify known error categories.
# ============================================================================
ERROR_PATTERNS = [
    {
        "pattern": r"error:\s+(.+\.(?:cpp|c|h|hpp)):(\d+):\d+:\s+error:\s+(.*)",
        "category": "C/C++ Compilation Error",
        "fix_hint": "Check the source file at the reported line. Common fixes: missing #include, typos in function/variable names, or incorrect types."
    },
    {
        "pattern": r"fatal error:\s+(.+\.h(?:pp)?): No such file or directory",
        "category": "Missing Header File",
        "fix_hint": "Add the package providing this header to DEPENDS in the recipe .bb file. Example: DEPENDS += \"libxyz\""
    },
    {
        "pattern": r"undefined reference to [`'](.+?)'",
        "category": "Linker Error (Undefined Reference)",
        "fix_hint": "The library providing this symbol is missing. Add it to LDFLAGS or DEPENDS in the recipe."
    },
    {
        "pattern": r"Applying patch (.+\.patch).*FAILED",
        "category": "Patch Application Failure",
        "fix_hint": "The patch no longer applies cleanly. Rebase or regenerate the patch against the current source."
    },
    {
        "pattern": r"Nothing PROVIDES '(.+?)'",
        "category": "Missing Yocto Recipe/Package",
        "fix_hint": "The required recipe is not in any included layer. Add the layer containing this recipe to bblayers.conf."
    },
    {
        "pattern": r"ERROR:\s+(.+?) do_fetch: Fetcher failure",
        "category": "Source Fetch Failure",
        "fix_hint": "Network issue or invalid SRC_URI. Check your internet connection, VPN, or verify the source URL in the recipe."
    },
    {
        "pattern": r"ERROR:\s+(.+?) do_configure: configure failed",
        "category": "Configure Step Failure",
        "fix_hint": "Check config.log for details. Common causes: missing build dependencies, incorrect EXTRA_OECONF flags."
    },
    {
        "pattern": r"out of memory|Cannot allocate memory|oom-kill",
        "category": "Out of Memory (OOM)",
        "fix_hint": "Reduce PARALLEL_MAKE or BB_NUMBER_THREADS in local.conf. Example: PARALLEL_MAKE = \"-j 4\""
    },
    {
        "pattern": r"No space left on device",
        "category": "Disk Full",
        "fix_hint": "Free disk space by running: bitbake -c cleansstate <recipe> on old builds, or delete unused tmp/ directories."
    },
]


# ============================================================================
# MCP TOOLS
# ============================================================================

@mcp.tool()
def list_build_targets() -> str:
    """
    List all available centralized build targets and their configurations.
    Use this to see which targets (K26, K26apl, etc.) are available for setup.
    """
    output = "📋 **Available Build Targets**:\n\n"
    output += "| Target | Description | Default Image | Branch |\n"
    output += "| :--- | :--- | :--- | :--- |\n"

    for target_name, config in BUILD_TARGETS.items():
        output += (
            f"| **{target_name}** | {config['description']} | "
            f"`{config['default_image']}` | `{config['branch']}` |\n"
        )

    output += f"\n**Total**: {len(BUILD_TARGETS)} target(s) available."
    return output


@mcp.tool()
def get_target_config(target_name: str) -> str:
    """
    Get the full configuration details for a specific build target.
    Returns repo URL, branch, MCF flags, premirror, sstatemirror, and default image.
    """
    key = target_name.lower().strip()
    if key not in BUILD_TARGETS:
        available = ", ".join(BUILD_TARGETS.keys())
        return f"❌ Target '{target_name}' not found. Available targets: {available}"

    config = BUILD_TARGETS[key]
    return (
        f"🎯 **Build Target: {key}**\n\n"
        f"- **Description**: {config['description']}\n"
        f"- **Repository**: `{config['repo']}`\n"
        f"- **Branch**: `{config['branch']}`\n"
        f"- **MCF Target**: `{config['mcf_target']}`\n"
        f"- **Parallel Jobs**: {config['mcf_parallel']}\n"
        f"- **Build Threads**: {config['mcf_build_threads']}\n"
        f"- **Premirror**: `{config['premirror']}`\n"
        f"- **Sstate Mirror**: `{config['sstatemirror']}`\n"
        f"- **Default Image**: `{config['default_image']}`\n"
    )


@mcp.tool()
def get_build_setup_script(target_name: str, workspace_name: str = "", branch: str = "") -> str:
    """
    Generate the complete build setup shell script for a specific target.
    This script clones the repo, checks out the branch, runs MCF, and sources the env.
    The bitbake command is provided as a comment — the user must confirm before running it.

    :param target_name: Build target name (e.g., 'k26', 'k26apl').
    :param workspace_name: Optional custom folder name. Defaults to 'build-<target>'.
    :param branch: Optional custom git branch to checkout (e.g. 'feature/camera-v2'). Overrides default target branch.
    """
    key = target_name.lower().strip()
    if key not in BUILD_TARGETS:
        available = ", ".join(BUILD_TARGETS.keys())
        return f"❌ Target '{target_name}' not found. Available targets: {available}"

    config = BUILD_TARGETS[key]
    folder = workspace_name if workspace_name else f"build-{key}"
    checkout_branch = branch.strip() if branch.strip() else config['branch']

    script = (
        f"#!/bin/bash\n"
        f"# ============================================\n"
        f"# Build Setup Script for: {key} (Branch: {checkout_branch})\n"
        f"# Generated by Build Automation Agent\n"
        f"# ============================================\n\n"
        f"# Phase 1: Clone and Configure (Automatic)\n"
        f"git clone {config['repo']} {folder}\n"
        f"cd {folder}\n"
        f"git checkout {checkout_branch}\n"
        f"./mcf {config['mcf_target']} -p {config['mcf_parallel']} -b {config['mcf_build_threads']} "
        f"--premirror={config['premirror']} "
        f"--sstatemirror={config['sstatemirror']}\n"
        f"source oe-init-build-env\n\n"
        f"# ============================================\n"
        f"# Phase 2: BUILD (REQUIRES USER CONFIRMATION)\n"
        f"# Do NOT run bitbake until user explicitly confirms.\n"
        f"# ============================================\n"
        f"# Full image:          bitbake {config['default_image']}\n"
        f"# Specific component:  bitbake <recipe-name>\n"
        f"# Force re-configure:  bitbake -C configure <recipe-name>\n"
        f"# Force re-compile:    bitbake -C compile <recipe-name>\n"
        f"# Clean:               bitbake -c clean <recipe-name>\n"
        f"# Clean all:           bitbake -c cleanall <recipe-name>\n"
        f"# Clean sstate:        bitbake -c cleansstate <recipe-name>\n"
        f"# DevShell:            bitbake -c devshell <recipe-name>\n"
    )

    return script


@mcp.tool()
def list_bitbake_tasks() -> str:
    """
    List all supported Bitbake task operations with their exact flags.
    Use this to understand what build/clean/debug operations are available.
    """
    output = "🛠️ **Supported Bitbake Task Operations**:\n\n"
    output += "| Task Name | Bitbake Flag | Description |\n"
    output += "| :--- | :--- | :--- |\n"

    for task_name, info in BITBAKE_TASKS.items():
        flag = info["flag"] if info["flag"] else "(none - default build)"
        output += f"| `{task_name}` | `{flag}` | {info['desc']} |\n"

    return output


@mcp.tool()
def get_bitbake_command(task: str, recipe: str) -> str:
    """
    Generate the exact bitbake command for a specific task and recipe.

    :param task: Task name (e.g., 'compile', 'clean', 'cleanall', 'cleansstate',
                 'force_compile', 'force_configure', 'devshell', 'build', 'env').
    :param recipe: Recipe/package name (e.g., 'starfish-media', 'gstreamer',
                   'lib32-starfish-global-flash').
    """
    task_key = task.lower().strip().replace("-", "_").replace(" ", "_")

    # Try direct match
    if task_key not in BITBAKE_TASKS:
        # Try fuzzy match
        for key in BITBAKE_TASKS:
            if task_key in key or key in task_key:
                task_key = key
                break
        else:
            available = ", ".join(BITBAKE_TASKS.keys())
            return f"❌ Unknown task '{task}'. Available tasks: {available}"

    info = BITBAKE_TASKS[task_key]
    flag = info["flag"]
    recipe_clean = recipe.strip()

    if flag:
        command = f"bitbake {flag} {recipe_clean}"
    else:
        command = f"bitbake {recipe_clean}"

    return (
        f"🚀 **Bitbake Command**:\n\n"
        f"```bash\n{command}\n```\n\n"
        f"**Task**: {info['desc']}\n"
        f"**Recipe**: `{recipe_clean}`\n\n"
        f"⚠️ Make sure `source oe-init-build-env` has been run in your build directory before executing this command."
    )


@mcp.tool()
def clone_repository(repo_name: str, server: str = "wall", destination_path: str = "") -> str:
    """
    Generate a git clone command with smart URL resolution for LGE servers (wall, gpro).
    Supports natural language repository names (e.g., 'settingsservice', 'pdm').

    :param repo_name: Name of the repository or component (e.g. 'settingsservice').
    :param server: 'wall' (default) or 'gpro'.
    :param destination_path: Optional local destination folder path.
    """
    server_lower = server.lower().strip()
    repo_key = repo_name.lower().strip()
    
    # Resolve server base URL
    if server_lower == "wall":
        base_url = "ssh://wall.lge.com/"
    elif server_lower == "gpro":
        base_url = "ssh://gpro.lge.com/"
    else:
        # If user provides a full git URL directly, or unknown server
        base_url = f"ssh://{server_lower}.lge.com/"
    
    # If the user provided a full ssh:// or http:// URL in repo_name, use it directly
    if repo_name.startswith("ssh://") or repo_name.startswith("http"):
        full_url = repo_name
    else:
        # Require a project path (e.g., 'starfish/settingsservice')
        if "/" not in repo_name:
            return (
                f"❌ **Missing Project Path**\n\n"
                f"Because there are many projects on `{server_lower}`, I cannot guess the exact location for `{repo_name}`.\n"
                f"Please provide the full project path. For example: `starfish/{repo_name}` or `tv-platform/{repo_name}`."
            )
            
        git_path = repo_name if repo_name.endswith(".git") else f"{repo_name}.git"
        full_url = f"{base_url}{git_path}"

    dest = f" {destination_path.strip()}" if destination_path.strip() else ""
    
    command = f"git clone {full_url}{dest}"
    
    return (
        f"📦 **Git Clone Command Generated**:\n\n"
        f"```bash\n{command}\n```\n\n"
        f"**Repository**: `{full_url}`\n"
        f"⚠️ Run this command in your terminal to clone the repository."
    )


@mcp.tool()
def devtool_modify(recipe: str, source_path: str = "", branch: str = "") -> str:
    """
    Generate the Yocto devtool command to build a component from a local directory or specific branch.
    Use this when a user wants to build local uncommitted changes, or check out a specific branch for a component.

    :param recipe: Recipe name (e.g., 'lib32-settingsservice'). Ensure it has 'lib32-' prefix if applicable.
    :param source_path: Path to the local source directory containing the code changes.
    :param branch: Optional specific branch to checkout during devtool modify.
    """
    recipe_clean = recipe.strip()
    
    if source_path:
        # Building from a local source tree
        command = f"devtool modify {recipe_clean} -srctree {source_path.strip()}"
        desc = f"Link recipe `{recipe_clean}` to local source directory `{source_path}`."
    elif branch:
        # Checking out a specific branch
        command = f"devtool modify {recipe_clean} --branch {branch.strip()}"
        desc = f"Modify recipe `{recipe_clean}` and checkout branch `{branch}`."
    else:
        return "❌ Error: You must provide either a 'source_path' or a 'branch' to devtool_modify."

    return (
        f"🛠️ **Devtool Modify Command**:\n\n"
        f"```bash\n{command}\n```\n\n"
        f"**Action**: {desc}\n\n"
        f"After running this, you can compile your changes by running `bitbake {recipe_clean}`."
    )


@mcp.tool()
def devtool_reset(recipe: str) -> str:
    """
    Generate the devtool reset command to unlink local source code for a recipe.

    :param recipe: Recipe name (e.g., 'lib32-settingsservice').
    """
    recipe_clean = recipe.strip()
    command = f"devtool reset {recipe_clean}"
    
    return (
        f"🔄 **Devtool Reset Command**:\n\n"
        f"```bash\n{command}\n```\n\n"
        f"This will unlink local sources and revert `{recipe_clean}` to the default Yocto fetcher."
    )


@mcp.tool()
def diagnose_build_log(log_text: str) -> str:
    """
    Analyze a Bitbake/Yocto build failure log and identify the root cause.
    Paste the error output from your terminal or provide the log file content.
    Returns the error category, exact error lines, and suggested fix.

    :param log_text: The build error log text (paste from terminal or log file content).
    """
    if not log_text or not log_text.strip():
        return "❌ No log text provided. Please paste the build error output."

    findings = []

    for pattern_info in ERROR_PATTERNS:
        matches = re.findall(pattern_info["pattern"], log_text, re.IGNORECASE | re.MULTILINE)
        if matches:
            finding = {
                "category": pattern_info["category"],
                "matches": matches[:5],  # Limit to first 5 matches
                "fix_hint": pattern_info["fix_hint"]
            }
            findings.append(finding)

    if not findings:
        # Extract any generic ERROR lines
        error_lines = re.findall(r"^.*(?:ERROR|error|FAILED|fatal).*$", log_text, re.MULTILINE | re.IGNORECASE)
        if error_lines:
            return (
                f"⚠️ **Build Error Detected** (Unclassified):\n\n"
                f"Found {len(error_lines)} error line(s):\n\n"
                + "\n".join([f"```\n{line.strip()}\n```" for line in error_lines[:10]])
                + "\n\n💡 **Suggestion**: Share more context from the log file for a more specific diagnosis."
            )
        return "✅ No known error patterns found in the provided log text. The build may have succeeded, or the error is in a different log file."

    # Build diagnostic report
    output = f"🔍 **Build Failure Diagnosis** ({len(findings)} issue(s) found):\n\n"

    for i, finding in enumerate(findings, 1):
        output += f"---\n\n### Issue #{i}: {finding['category']}\n\n"

        output += "**Error Details**:\n"
        for match in finding["matches"]:
            if isinstance(match, tuple):
                output += f"- `{' : '.join(match)}`\n"
            else:
                output += f"- `{match}`\n"

        output += f"\n💡 **Suggested Fix**: {finding['fix_hint']}\n\n"

    return output


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
    print("Starting Build Automation Agent MCP Server on port 8000 (SSE Transport)...")

    # Wrap Starlette app with HostHeaderBypassMiddleware
    wrapped_app = HostHeaderBypassMiddleware(app)

    uvicorn.run(wrapped_app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")
