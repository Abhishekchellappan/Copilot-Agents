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

from config import TEMPLATES_DIR, SERVER_PORT, WORKSPACE_ROOT
from rag_engine import search_standards, search_api_registry, get_collection_stats
from ast_parser import parse_file, find_symbol, scan_directory
from bitbake_parser import parse_recipe, parse_layer_conf, validate_recipe, build_dependency_graph

mcp = FastMCP("Code Implementation Agent")

@mcp.tool()
def template_scaffolder(component_type: str, component_name: str, target_path: str, language: str = 'cpp') -> str:
    """
    Generates plugin/service skeletons based on company Golden Templates. Supports: luna_service, yocto_recipe, cpp_daemon, dart_plugin, java_service, gtest_suite. Writes files directly to the specified target_path in the workspace.
    """
    os.makedirs(target_path, exist_ok=True)
    created_files = []

    if component_type == 'cpp_daemon' or component_type == 'luna_service':
        comp_dir = os.path.join(target_path, component_name)
        src_dir = os.path.join(comp_dir, 'src')
        os.makedirs(src_dir, exist_ok=True)
        
        cmake_content = f"cmake_minimum_required(VERSION 3.10)\nproject({component_name})\nset(CMAKE_CXX_STANDARD 17)\nadd_executable({component_name} src/{component_name}.cpp)\n"
        cmake_path = os.path.join(comp_dir, "CMakeLists.txt")
        with open(cmake_path, "w") as f:
            f.write(cmake_content)
        created_files.append(cmake_path)
        
        cpp_content = f"#include <iostream>\n#include \"{component_name}.h\"\n\n// PmLogLib placeholder\n\nint main(int argc, char** argv) {{\n    // signal handling stub\n    std::cout << \"Hello from {component_name}\" << std::endl;\n    return 0;\n}}\n"
        if component_type == 'luna_service':
            cpp_content += "\n// LSRegister and LSCall stubs\n"
        cpp_path = os.path.join(src_dir, f"{component_name}.cpp")
        with open(cpp_path, "w") as f:
            f.write(cpp_content)
        created_files.append(cpp_path)
        
        header_content = f"#ifndef {component_name.upper()}_H\n#define {component_name.upper()}_H\n\nclass {component_name} {{\npublic:\n    {component_name}();\n    ~{component_name}();\n}};\n\n#endif // {component_name.upper()}_H\n"
        header_path = os.path.join(src_dir, f"{component_name}.h")
        with open(header_path, "w") as f:
            f.write(header_content)
        created_files.append(header_path)
        
        readme_path = os.path.join(comp_dir, "README.md")
        with open(readme_path, "w") as f:
            f.write(f"# {component_name}\n")
        created_files.append(readme_path)

    elif component_type == 'yocto_recipe':
        recipe_content = f"SUMMARY = \"{component_name} recipe\"\nDESCRIPTION = \"Recipe for {component_name}\"\nLICENSE = \"Apache-2.0\"\nLIC_FILES_CHKSUM = \"\"\n\nSRC_URI = \"\"\nDEPENDS = \"\"\n\ninherit cmake\n"
        recipe_path = os.path.join(target_path, f"{component_name}.bb")
        with open(recipe_path, "w") as f:
            f.write(recipe_content)
        created_files.append(recipe_path)

    elif component_type == 'gtest_suite':
        tests_dir = os.path.join(target_path, 'tests')
        os.makedirs(tests_dir, exist_ok=True)
        test_content = f"#include <gtest/gtest.h>\n\nTEST({component_name}Test, BasicAssertion) {{\n    EXPECT_EQ(1, 1);\n}}\n"
        test_path = os.path.join(tests_dir, f"test_{component_name}.cpp")
        with open(test_path, "w") as f:
            f.write(test_content)
        created_files.append(test_path)

    elif component_type == 'dart_plugin':
        yaml_content = f"name: {component_name}\ndescription: A new Flutter plugin project.\nversion: 0.0.1\n"
        yaml_path = os.path.join(target_path, "pubspec.yaml")
        with open(yaml_path, "w") as f:
            f.write(yaml_content)
        created_files.append(yaml_path)
        
        lib_dir = os.path.join(target_path, 'lib')
        os.makedirs(lib_dir, exist_ok=True)
        dart_content = f"class {component_name.capitalize()} {{\n  // Basic class stub\n}}\n"
        dart_path = os.path.join(lib_dir, f"{component_name}.dart")
        with open(dart_path, "w") as f:
            f.write(dart_content)
        created_files.append(dart_path)

    return f"Created {len(created_files)} files:\n" + "\n".join(created_files)

@mcp.tool()
def workspace_code_analyzer(file_path: str = '', symbol_name: str = '', directory_path: str = '', extensions: str = '.cpp,.h,.c,.java') -> str:
    """
    Uses Tree-sitter AST parsing to precisely extract function signatures, classes, and IPC structs from the mounted workspace. Use this tool to understand existing code structure before generating new code. IMPORTANT: Always call this tool BEFORE generating code that integrates with existing sources.
    """
    output = []
    if file_path:
        if symbol_name:
            output.append(f"Symbol '{symbol_name}' in {file_path}:")
            output.append(str(find_symbol(file_path, symbol_name)))
        else:
            output.append(f"Parsing file {file_path}:")
            output.append(str(parse_file(file_path)))
            
    if directory_path:
        ext_list = [e.strip() for e in extensions.split(',')]
        output.append(f"Scanning directory {directory_path} for extensions {ext_list}:")
        output.append(str(scan_directory(directory_path, ext_list, symbol_name)))
        
    return "\n".join(output)

@mcp.tool()
def api_registry_search(query: str, language_filter: str = '', top_k: int = 5) -> str:
    """
    Queries the local ChromaDB vector store for company coding standards, API documentation, OpenAPI/Protobuf definitions, and IPC patterns. Use this tool to find correct API signatures, struct definitions, and coding conventions BEFORE writing any code.
    """
    output = []
    output.append("Standards Search Results:")
    output.append(str(search_standards(query, top_k)))
    
    output.append("\nAPI Registry Search Results:")
    output.append(str(search_api_registry(query, language_filter, top_k)))
    
    output.append("\nCollection Stats:")
    output.append(str(get_collection_stats()))
    
    return "\n".join(output)

@mcp.tool()
def bitbake_layer_validator(recipe_path: str, layer_conf_path: str = '', scan_deps_dir: str = '') -> str:
    """
    Parses and validates BitBake recipe (.bb/.bbappend) files and layer.conf. Checks DEPENDS/RDEPENDS for missing or circular dependencies. Use this tool after generating any Yocto recipe to validate it before building.
    """
    output = []
    
    output.append(f"Parsed Recipe {recipe_path}:")
    output.append(str(parse_recipe(recipe_path)))
    
    if layer_conf_path:
        output.append(f"\nParsed Layer Conf {layer_conf_path}:")
        output.append(str(parse_layer_conf(layer_conf_path)))
        
    output.append(f"\nValidation Results for {recipe_path}:")
    output.append(str(validate_recipe(recipe_path, layer_conf_path)))
    
    if scan_deps_dir:
        output.append(f"\nDependency Graph for {scan_deps_dir}:")
        output.append(str(build_dependency_graph(scan_deps_dir)))
        
    return "\n".join(output)

class HostHeaderBypassMiddleware:
    def __init__(self, app):
        self.app = app
        
    async def __call__(self, scope, receive, send):
        if scope.get('type') in ('http', 'websocket'):
            headers = []
            for k, v in scope.get('headers', []):
                if k.lower() == b'host':
                    headers.append((b'host', b'localhost:8000'))
                else:
                    headers.append((k, v))
            scope['headers'] = headers
        await self.app(scope, receive, send)

app = mcp.sse_app()

async def health_check(request: Request) -> Response:
    """Health check endpoint for Kubernetes liveness/readiness probes."""
    return Response(content='OK', status_code=200)

app.routes.append(Route('/health', health_check, methods=['GET']))


# ============================================================================
# Server Startup
# ============================================================================
if __name__ == '__main__':
    import uvicorn

    print(f"🏗️ Code Implementation Agent starting on port {SERVER_PORT} (SSE Transport)...")
    print(f"📡 SSE endpoint: http://0.0.0.0:{SERVER_PORT}/sse")
    print(f"📂 Workspace root: {WORKSPACE_ROOT}")
    print(f"📐 Golden Templates: {TEMPLATES_DIR}")

    # Initialize RAG stores
    stats = get_collection_stats()
    print(f"📊 Standards indexed: {stats.get('standards_count', 0)}, APIs indexed: {stats.get('api_count', 0)}")
    print("✅ Code Implementation Agent ready!")

    # Wrap Starlette app with HostHeaderBypassMiddleware
    wrapped_app = HostHeaderBypassMiddleware(app)

    uvicorn.run(
        wrapped_app,
        host="0.0.0.0",
        port=SERVER_PORT,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
