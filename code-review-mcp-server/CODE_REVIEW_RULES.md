# Master C++ & API Code Review Rulebook

This document defines the complete code review guidelines for our department, incorporating:
1. **ISO C++ Core Guidelines** (https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines.md)
2. **Google C++ Style Guide** (https://google.github.io/styleguide/cppguide.html)
3. **HS Collaboration Center API Design & Development Rules** (http://collab.lge.com/main/spaces/LGSIHA/pages/3749133854/API+Design+Development+Rules)
4. **LG / webOS Platform & Luna Bus Standards**

---

## 1. Philosophy & General Principles (C++ Core Guidelines P.1 - P.13)
- **P.1**: Express ideas directly in code (e.g., use `std::find` instead of manual `for` loops).
- **P.2**: Write in ISO Standard C++.
- **P.3**: Express intent — prefer `const`, `constexpr`, and explicit types.
- **P.4**: Type-safe code — avoid raw typecasts, union abuses, and uninitialized variables.
- **P.7**: Catch run-time errors early; do not ignore return codes or exceptions.
- **P.10**: Prefer immutable data (`const`) over mutable data.

---

## 2. Interfaces & Function Signatures (C++ Core Guidelines I.1 - I.30, F.1 - F.60)
- **I.2**: Avoid global variables — pass dependencies explicitly.
- **I.4**: Make interfaces precisely and strongly typed (use `enum class`, strong typedefs).
- **I.11**: Never pass an array as a single pointer `T*` — use `std::span<T>` or `std::array`.
- **F.16**: Pass parameters efficiently:
  - Cheap types (`int`, `float`, `enum`, `std::string_view`): Pass by **value**.
  - Large read-only objects: Pass by **`const T&`**.
  - Sink parameters (ownership transfer): Pass by **`T&&`** or **value**.
- **F.20**: Return multiple values using `std::tuple`, `std::pair`, or a named `struct`.
- **F.43**: Never return a reference or pointer to a local/stack variable.

---

## 3. Resource Management & Smart Pointers (C++ Core Guidelines R.1 - R.37)
- **R.1**: RAII (Resource Acquisition Is Initialization) — enforce resource cleanup in destructors.
- **R.3**: Raw pointers (`T*`) are **non-owning**. Never call `delete` on a raw pointer.
- **R.11**: Use `std::unique_ptr` for single-owner dynamic allocation.
- **R.12**: Use `std::shared_ptr` ONLY when ownership is genuinely shared.
- **R.13**: Use `std::make_unique()` and `std::make_shared()` to allocate smart pointers.
- **R.30**: Avoid `void*` pointers — use `std::any` or templates.

---

## 4. Classes & Class Hierarchies (C++ Core Guidelines C.1 - C.183)
- **C.20 / C.21 (Rule of 0 / 5)**: If you define a custom destructor, copy/move constructor, or assignment operator, explicitly define or delete all 5.
- **C.35**: Make base class destructors `virtual` and `public`, or `non-virtual` and `protected`.
- **C.41**: Always use `override` or `final` explicitly when overriding a virtual function.
- **C.46**: Single-argument constructors must be `explicit` to prevent implicit type conversions.
- **C.131**: Avoid `virtual` function calls in constructors or destructors.

---

## 5. Expressions, Statements & Casting (C++ Core Guidelines ES.1 - ES.106)
- **ES.20**: Always initialize variables at declaration (`int x = 0;`).
- **ES.45**: Avoid magic numbers — use `constexpr` or `enum class`.
- **ES.48**: **NO C-style casts** (`(int)x`). Use `static_cast`, `const_cast`, or `reinterpret_cast`.
- **ES.78**: Always include a `default:` label in `switch` statements.
- **ES.103**: Do not use `goto`.

---

## 6. Concurrency & Thread Safety (C++ Core Guidelines CP.1 - CP.50)
- **CP.1**: Assume multi-threaded execution unless proven single-threaded.
- **CP.20**: Use RAII locks (`std::lock_guard`, `std::unique_lock`, `std::scoped_lock`). Never call `.lock()` / `.unlock()` manually.
- **CP.26**: Avoid data races — protect shared mutable state with `std::mutex` or `std::atomic`.
- **CP.42**: Do not use `volatile` for thread synchronization (use `std::atomic`).

---

## 7. Google C++ Naming & Formatting Conventions
- **Classes / Structs / Enums**: `PascalCase` (e.g., `CameraPipelineManager`, `FrameBuffer`).
- **Local Variables**: `snake_case` (e.g., `frame_count`, `buffer_size`).
- **Class Private Members**: `snake_case_` with trailing underscore (e.g., `frame_count_`, `mutex_`).
- **Constants**: `kPascalCase` (e.g., `kMaxFrameRate`, `kDefaultTimeoutMs`).
- **Functions / Methods**: `PascalCase` or `camelCase` (e.g., `ProcessFrame()`, `initializePipeline()`).
- **Include Guards**: `#ifndef PROJECT_PATH_FILENAME_H_` format.
- **Namespaces**: `snake_case` (e.g., `namespace starfish::camera`).

---

## 8. HS Collaboration Center API Design & Development Rules
*(Reference: http://collab.lge.com/main/spaces/LGSIHA/pages/3749133854/API+Design+Development+Rules)*

### RESTful Endpoint Naming
- Use plural nouns for resources (e.g., `/api/v1/devices`, `/api/v1/pipelines`).
- Use lowercase `kebab-case` or `snake_case` in URL paths; avoid camelCase in URLs.
- Use standard HTTP methods: `GET` (read), `POST` (create), `PUT` (full update), `PATCH` (partial update), `DELETE` (remove).

### API Versioning & Backwards Compatibility
- All public APIs must include API versioning in the URL path (e.g., `/api/v1/...` or `com.webos.service.pdm.v1`).
- Breaking changes require incrementing the major version number (`v2`).

### JSON Payload & Error Response Standard
- Response JSON keys must maintain consistent casing (`camelCase` or `snake_case`) across all endpoints.
- Errors must use standard HTTP status codes (`400 Bad Request`, `401 Unauthorized`, `403 Forbidden`, `404 Not Found`, `500 Internal Error`).
- Error response payloads must follow the HS standard format:
  ```json
  {
    "errorCode": "ERR_INVALID_PARAM",
    "errorMessage": "Detailed error description",
    "timestamp": "2026-08-04T10:00:00Z"
  }
  ```

### Luna Bus / LS2 Service API Rules (webOS / LGSIHA)
- Luna Bus method names must use `lowerCamelCase` (e.g., `getDeviceInfo`, `startPipeline`).
- LS2 service methods must validate incoming JSON schema and return `"returnValue": true/false`.
- Required security permissions must be declared in `.role.json` and `.perm.json` manifests.

---

## 9. LG / webOS Platform & Architecture Rules
- Use `ACP_SPECIFIC` conditionals for platform-dependent code paths.
- Target link library names must be platform-specific (not generic).
- Use `lib32-` prefix for 32-bit multilib targets in Yocto recipes and CMake targets.
- Include legal copyright header: `Copyright (c) 2017-2026 LG Electronics, Inc.`

---

---

## 11. Master Dart & Flutter Code Review Guidelines

### A. Lifecycle & Memory Management (Critical)
- **Controller Disposal**: Every `AnimationController`, `TextEditingController`, `ScrollController`, `TabController`, `StreamController`, or `WebViewController` instantiated in a `StatefulWidget` **MUST** be explicitly disposed in `dispose()`.
- **`if (!mounted) return;` Check**: Always verify `if (mounted)` or `if (!mounted) return;` before invoking `setState()` after an `await` async gap.
- **Timer & Stream Cancellation**: Every `Timer`, `Timer.periodic()`, or `StreamSubscription` created within a widget or service must call `.cancel()` inside `dispose()` or cleanup handlers.

### B. Null Safety & `late` Keyword Rules
- **No Unsafe Non-Null Assertions (`!`)**: Avoid using `!` to force non-nullability unless preceded by an explicit null check. Use `?.` or `??` fallbacks.
- **No `late` as Null-Safety Bypass**: Do not declare variables as `late` if they are not guaranteed to be initialized before access. Use nullable types (`Type?`) with explicit null guards instead to prevent `LateInitializationError` crashes.
- **Prefer `late final` for State Controllers**: State properties initialized in `initState()` should be marked `late final` to enforce immutability during widget lifecycle.
- **Constructor Initializer Lists**: Prefer initializing fields in the constructor initializer list over using `late`.

### C. Flutter Performance & Element Tree Optimization
- **`const` Constructors**: Always mark immutable widgets with `const` to prevent unnecessary widget tree re-renders during `setState()`.
- **Widget Extraction**: Extract complex UI sub-trees into standalone `StatelessWidget` or `StatefulWidget` classes rather than helper functions returning `Widget` (e.g. `Widget _buildItem()`).
- **No Heavy Operations in `build()`**: Never execute network requests, file I/O, database reads, or heavy computation synchronously inside the `build()` method.
- **Embedded Memory Image Caching (webOS)**: Always pass `cacheWidth` and/or `cacheHeight` to `Image.network` or `Image.asset` to prevent full-resolution uncompressed decoding into GPU memory.

### D. Dart Language Idioms & Security
- **No Raw `print()`**: Use `developer.log()` or a structured logging service instead of `print()` to prevent leaking sensitive debug information.
- **Collection Operators**: Use collection `if`, collection `for`, and spread operators (`...`, `...?`) instead of manual `for` loops and `.add()`.
- **Strong Typing**: Avoid `dynamic` type annotations; use explicit types, generics, or `Object?`.
- **Naming Conventions**: `PascalCase` for types/widgets, `camelCase` for members/functions, `lowercase_with_underscores` for files/libraries.

---

## 12. Severity Classification Matrix

| Severity | Definition | Action Required |
| :--- | :--- | :--- |
| **Critical** | Hardcoded secrets, memory leaks (undisposed controllers), `setState` on unmounted widget, data races | Must fix immediately |
| **Error** | C-style casts, missing `override`, raw `delete`, unsafe `late`/`!` usage, API schema violations | Must fix before merge |
| **Warning** | Missing `const` widgets, missing `cacheWidth`, magic numbers, non-`const` refs, long functions | Recommended fix |
| **Info** | Formatting, TODO comments, naming style suggestions, raw `print()` statements | Optional fix |
