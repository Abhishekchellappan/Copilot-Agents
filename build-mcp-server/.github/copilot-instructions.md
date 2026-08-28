# GitHub Copilot Instructions - Build Automation Agent

These instructions define the interactive workflow rules for Copilot when working
with the Build Automation Agent (`@build-automation-agent`) and Yocto/Bitbake builds.

---

## 🏗️ Build Environment Setup Workflow

When the user asks to set up a build environment for a target (e.g., K26, K26apl):

### Phase 1: Environment Detection (Check FIRST)
1. Check if the user is **already inside an existing build directory** (look for `oe-init-build-env`, `conf/local.conf`, or `build/` folder).
2. If an existing build environment is detected:
   - Do NOT clone or create a new directory.
   - Simply run `source oe-init-build-env` in the current directory.
   - Skip directly to Phase 3 (Interactive Build Choice).
3. If no existing build environment is found, proceed to Phase 2.

### Phase 2: New Environment Setup (Automatic)
1. Extract the requested target (e.g., K26, K26apl) and optional custom branch (e.g., `feature/camera-v2`) from the user prompt.
2. Use `@build-automation-agent` to call `get_build_setup_script(target_name="<target>", branch="<branch_if_provided>")`.
3. Execute the returned setup commands in the VS Code terminal:
   - `git clone <repo> build-<target>`
   - `cd build-<target>`
   - `git checkout <branch>`
   - `./mcf <target> -p <parallel> -b <threads> --premirror=<path> --sstatemirror=<path>`
   - `source oe-init-build-env`
4. After all setup commands complete successfully, proceed to Phase 3.

### Phase 3: Interactive Build Choice ⚠️ (MANDATORY PAUSE)
**STOP** after environment setup and present the user with these options:

> "✅ Build environment for **<target>** is ready!
>
> What would you like to do next?
> 1. 🏗️ **Full Image Build** (`bitbake <default-image>`)
> 2. 📦 **Build Specific Component** (specify recipe name)
> 3. 🔄 **Force Re-configure** a component (`bitbake -C configure <recipe>`)
> 4. 🔄 **Force Re-compile** a component (`bitbake -C compile <recipe>`)
> 5. 🧹 **Clean** a component (`bitbake -c clean <recipe>`)
> 6. 🧹 **Clean All** a component (`bitbake -c cleanall <recipe>`)
> 7. 🧹 **Clean Sstate Cache** for a component (`bitbake -c cleansstate <recipe>`)
> 8. 🐚 **Open DevShell** for a component (`bitbake -c devshell <recipe>`)
> 9. ⏭️ **Skip** — leave terminal ready for manual commands
>
> Please tell me your choice and the component/recipe name if applicable."

**Do NOT execute ANY bitbake command until the user explicitly provides their choice.**

---

## 📦 Git Repository Cloning (`wall` and `gpro`)

When the user asks to clone a repository:
1. Extract the repository name/component (e.g., `settingsservice`, `pdm`).
2. Extract the server if mentioned (`wall` or `gpro`), default to `wall`.
3. Extract the destination path if provided.
4. Use `@build-automation-agent` to call `clone_repository(repo_name="<name>", server="<server>", destination_path="<path>")`.
5. Run the generated `git clone` command in the VS Code terminal.

---

## 🛠️ Advanced Component Build Rules (`devtool`)

When the user asks to build local code changes or build a specific branch of a component:
1. If building local changes in a folder: Use `@build-automation-agent` to call `devtool_modify(recipe="lib32-<recipe>", source_path="<path>")`.
2. If building a specific branch: Use `@build-automation-agent` to call `devtool_modify(recipe="lib32-<recipe>", branch="<branch>")`.
3. If resetting a component: Use `@build-automation-agent` to call `devtool_reset(recipe="lib32-<recipe>")`.
4. Run the generated `devtool` command in the terminal.
5. After `devtool modify`, run the appropriate `bitbake` command (e.g. `bitbake lib32-<recipe>`).

---

## 📦 32-Bit Multilib (`lib32-`) Auto-Prefixing Rules

For multilib build targets (such as K26, K26apl):
- If the user provides a component/recipe name without the `lib32-` prefix (e.g., `servicemanager` or `starfish-media`), **automatically prepend `lib32-`** when generating and running bitbake commands (e.g. `bitbake lib32-servicemanager` or `bitbake -c cleanall lib32-servicemanager`).
- If the recipe name already starts with `lib32-`, do not add it again.
- Full image targets (e.g., `lib32-starfish-global-flash`) already contain `lib32-`.

---

## 🛠️ Bitbake Task Mapping Rules

When the user asks to run a Bitbake operation, map their request to the correct command:

| User Says | Execute |
| :--- | :--- |
| "Build full image" | `bitbake <default-image>` |
| "Build / compile `<recipe>`" | `bitbake lib32-<recipe>` |
| "Compile only `<recipe>`" | `bitbake -c compile lib32-<recipe>` |
| "Force re-configure `<recipe>`" | `bitbake -C configure lib32-<recipe>` |
| "Force re-compile `<recipe>`" | `bitbake -C compile lib32-<recipe>` |
| "Clean `<recipe>`" | `bitbake -c clean lib32-<recipe>` |
| "Clean all `<recipe>`" | `bitbake -c cleanall lib32-<recipe>` |
| "Clean sstate / sstate cache `<recipe>`" | `bitbake -c cleansstate lib32-<recipe>` |
| "Open devshell for `<recipe>`" | `bitbake -c devshell lib32-<recipe>` |
| "Show environment for `<recipe>`" | `bitbake -e lib32-<recipe>` |
| "Fetch sources for `<recipe>`" | `bitbake -c fetch lib32-<recipe>` |
| "List tasks for `<recipe>`" | `bitbake -c listtasks lib32-<recipe>` |

**IMPORTANT**: Always verify that `source oe-init-build-env` has been executed in the
current terminal session before running any bitbake command. If not, run it first.

---

## 🔍 Build Error Diagnosis Workflow

When a bitbake build fails and the user asks for help diagnosing:

1. Look for the error log file. Common locations:
   - Terminal output (immediate error lines)
   - `tmp/work/<arch>/<recipe>/<version>/temp/log.do_compile`
   - `tmp/work/<arch>/<recipe>/<version>/temp/log.do_configure`
   - `tmp/work/<arch>/<recipe>/<version>/temp/log.do_fetch`

2. Read the relevant log file content.

3. Use `@build-automation-agent` to call `diagnose_build_log` with the log text.

4. Present the diagnosis to the user with:
   - Error category (e.g., "C++ Compilation Error", "Missing Header", "Patch Failure")
   - Exact error lines with file names and line numbers
   - Suggested fix

5. If the fix involves editing a source file or recipe:
   - Open the file in VS Code
   - Apply the fix
   - Ask the user if they want to re-run the failed bitbake task

---

## 📋 General Rules

1. **Never run bitbake without user confirmation** in Phase 3.
2. **Always source the build environment** before any bitbake command.
3. **Never re-clone** if user is already in an existing build directory.
4. **When multiple build directories exist**, ask the user which one to use.
5. **For long-running builds**, inform the user of estimated time if possible.
