import os
import re
from typing import Dict, Any, List, Optional
from config import WORKSPACE_ROOT, SUPPORTED_LANGUAGES

# Optional imports for tree-sitter
try:
    import tree_sitter
    from tree_sitter import Language, Parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    print("WARNING: tree_sitter not installed. Falling back to regex-based parsing.", flush=True)

def log(msg: str):
    """Log a message using print with flush=True."""
    print(msg, flush=True)

def _ext_to_lang(ext: str) -> str:
    """Map file extension to language name."""
    ext = ext.lower()
    if ext in ['.c', '.h']:
        return 'c'
    elif ext in ['.cpp', '.cc', '.hpp']:
        return 'cpp'
    elif ext == '.java':
        return 'java'
    return 'unknown'

def _regex_parse_file(file_path: str, ext: str) -> dict:
    """Regex fallback for parsing a source file."""
    result = {
        "file_path": file_path,
        "language": _ext_to_lang(ext),
        "functions": [],
        "classes": [],
        "includes": []
    }
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if ext in ['.c', '.cpp', '.cc', '.h', '.hpp']:
            # Includes
            includes = re.findall(r'^#include\s*[<"]([^>"]+)[>"]', content, re.MULTILINE)
            result['includes'] = includes
            
            # Simple function matches (very basic approximation)
            funcs = re.findall(r'^(?:[\w:<>\[\]*&]+\s+)+(\w+)\s*\([^)]*\)\s*(?:const)?\s*(?:noexcept)?\s*\{', content, re.MULTILINE)
            result['functions'] = list(set(funcs))
            
            # Simple class/struct matches
            classes = re.findall(r'^(?:class|struct)\s+(\w+)', content, re.MULTILINE)
            result['classes'] = list(set(classes))
            
        elif ext == '.java':
            # Imports
            imports = re.findall(r'^import\s+([^;]+);', content, re.MULTILINE)
            result['includes'] = imports
            
            # Simple method matches
            methods = re.findall(r'(?:public|protected|private|static|\s)+[\w\<\>\[\]]+\s+(\w+)\s*\([^)]*\)\s*\{', content)
            result['functions'] = list(set(methods))
            
            # Simple class matches
            classes = re.findall(r'(?:public|protected|private|static|\s)+class\s+(\w+)', content)
            result['classes'] = list(set(classes))
            
    except Exception as e:
        log(f"Error parsing file {file_path} with regex: {e}")
        
    return result

def _regex_find_symbol(file_path: str, symbol_name: str, ext: str) -> dict:
    """Regex fallback for finding a symbol definition."""
    result = {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for i, line in enumerate(lines):
            if symbol_name in line:
                if 'class ' in line or 'struct ' in line or 'enum ' in line:
                    result = {
                        "name": symbol_name,
                        "type": "class/struct/enum",
                        "definition": line.strip(),
                        "line_range": (i+1, i+1),
                        "dependencies": []
                    }
                    break
                elif '(' in line and ')' in line and '{' in line:
                    result = {
                        "name": symbol_name,
                        "type": "function",
                        "definition": line.strip(),
                        "line_range": (i+1, i+1),
                        "dependencies": []
                    }
                    break
    except Exception as e:
        log(f"Error finding symbol {symbol_name} in {file_path} with regex: {e}")
    return result

def parse_file(file_path: str) -> dict:
    """
    Parses a source file and returns its AST structure summary including:
    - File path
    - Language detected (based on extension: .c, .cpp, .cc, .h, .hpp, .java)
    - List of functions/methods with signatures
    - List of classes/structs with member names
    - List of includes/imports
    """
    if not os.path.exists(file_path):
        log(f"File not found: {file_path}")
        return {}

    _, ext = os.path.splitext(file_path)
    if ext not in ['.c', '.cpp', '.cc', '.h', '.hpp', '.java']:
        log(f"Unsupported file extension: {ext}")
        return {}

    if not TREE_SITTER_AVAILABLE:
        return _regex_parse_file(file_path, ext)
        
    try:
        # Load language grammars dynamically if available
        # Note: tree_sitter normally requires compiled binaries for languages.
        # Assuming tree-sitter packages like tree-sitter-c are installed.
        import tree_sitter_c
        import tree_sitter_cpp
        import tree_sitter_java
        
        lang_str = _ext_to_lang(ext)
        if lang_str == 'c':
            lang = Language(tree_sitter_c.language(), 'c')
        elif lang_str == 'cpp':
            lang = Language(tree_sitter_cpp.language(), 'cpp')
        elif lang_str == 'java':
            lang = Language(tree_sitter_java.language(), 'java')
        else:
            return _regex_parse_file(file_path, ext)
            
        parser = Parser()
        parser.set_language(lang)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
            
        tree = parser.parse(bytes(source, "utf8"))
        
        result = {
            "file_path": file_path,
            "language": lang_str,
            "functions": [],
            "classes": [],
            "includes": []
        }
        
        # Simple AST traversal to collect information
        def traverse(node):
            if node.type in ['function_definition', 'method_declaration']:
                line = source[node.start_byte:node.end_byte].split('\\n')[0]
                result['functions'].append(line)
            elif node.type in ['class_specifier', 'struct_specifier', 'class_declaration']:
                line = source[node.start_byte:node.end_byte].split('\\n')[0]
                result['classes'].append(line)
            elif node.type in ['preproc_include', 'import_declaration']:
                result['includes'].append(source[node.start_byte:node.end_byte])
                
            for child in node.children:
                traverse(child)
                
        traverse(tree.root_node)
        return result
        
    except Exception as e:
        log(f"Tree-sitter parsing failed for {file_path}, falling back to regex: {e}")
        return _regex_parse_file(file_path, ext)

def find_symbol(file_path: str, symbol_name: str) -> dict:
    """
    Searches a specific file for a named symbol (function, class, struct, enum).
    Returns a dictionary containing:
    - Symbol name, type (function/class/struct/enum)
    - Full signature/definition text
    - Line number range
    - Dependencies (what it includes/imports)
    """
    if not os.path.exists(file_path):
        log(f"File not found: {file_path}")
        return {}
        
    _, ext = os.path.splitext(file_path)
    if ext not in ['.c', '.cpp', '.cc', '.h', '.hpp', '.java']:
        log(f"Unsupported file extension: {ext}")
        return {}
    
    if not TREE_SITTER_AVAILABLE:
        return _regex_find_symbol(file_path, symbol_name, ext)
        
    try:
        # Fallback to regex for this simple implementation if AST search gets complicated
        return _regex_find_symbol(file_path, symbol_name, ext)
    except Exception as e:
        log(f"Error finding symbol {symbol_name} in {file_path}: {e}")
        return {}

def scan_directory(directory_path: str, extensions: list[str] = None, symbol_name: str = '') -> list[dict]:
    """
    Recursively scans a directory for source files matching extensions and optionally filters by symbol name.
    """
    if not os.path.exists(directory_path):
        log(f"Directory not found: {directory_path}")
        return []
        
    if extensions is None:
        extensions = ['.c', '.cpp', '.cc', '.h', '.hpp', '.java']
        
    results = []
    try:
        for root, _, files in os.walk(directory_path):
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext in extensions:
                    path = os.path.join(root, file)
                    if symbol_name:
                        sym_info = find_symbol(path, symbol_name)
                        if sym_info:
                            results.append({
                                "file": path,
                                "symbol": sym_info
                            })
                    else:
                        file_info = parse_file(path)
                        if file_info:
                            results.append(file_info)
    except Exception as e:
        log(f"Error scanning directory {directory_path}: {e}")
                        
    return results
