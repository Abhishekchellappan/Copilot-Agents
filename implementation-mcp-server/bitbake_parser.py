import os
import re
import glob
import networkx as nx
from typing import Dict, List, Any

# Attempt to import WORKSPACE_ROOT from config
try:
    from config import WORKSPACE_ROOT
except ImportError:
    WORKSPACE_ROOT = os.getcwd()

def _parse_file(filepath: str) -> Dict[str, Any]:
    """Helper to parse a BitBake file (recipe or conf)."""
    parsed_data = {}
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}", flush=True)
        return parsed_data

    # Regex for standard variables (e.g., VAR = "value", VAR += "value", VAR ?= "value")
    var_re = re.compile(r'^([a-zA-Z0-9_.-]+)\s*(\+?=|\?=|:=|=)\s*"(.*?)"', re.MULTILINE | re.DOTALL)
    
    # Regex for unquoted assignments (less common but happens)
    var_unquoted_re = re.compile(r'^([a-zA-Z0-9_.-]+)\s*(\+?=|\?=|:=|=)\s*([^\s"]+)', re.MULTILINE)
    
    # Regex for tasks (e.g., do_compile() { ... })
    task_re = re.compile(r'^(do_[a-zA-Z0-9_.-]+)\s*\(\)\s*\{([^}]*)\}', re.MULTILINE | re.DOTALL)
    
    # Regex for inherit
    inherit_re = re.compile(r'^inherit\s+(.*)', re.MULTILINE)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

        # Extract variables
        for match in var_re.finditer(content):
            var_name, op, var_value = match.groups()
            var_value = var_value.strip()
            if var_name in parsed_data and op == '+=':
                parsed_data[var_name] += f" {var_value}"
            else:
                parsed_data[var_name] = var_value
        
        # Extract unquoted variables
        for match in var_unquoted_re.finditer(content):
            var_name, op, var_value = match.groups()
            var_value = var_value.strip()
            if var_name not in parsed_data:
                if op == '+=' and var_name in parsed_data:
                     parsed_data[var_name] += f" {var_value}"
                else:
                     parsed_data[var_name] = var_value

        # Extract tasks
        for match in task_re.finditer(content):
            task_name, task_content = match.groups()
            parsed_data[task_name] = task_content.strip()

        # Extract inherit
        inherits = []
        for match in inherit_re.finditer(content):
            inherits.extend(match.group(1).split())
        if inherits:
            parsed_data['inherit'] = " ".join(inherits)

    return parsed_data

def parse_recipe(recipe_path: str) -> dict:
    """
    Parses a BitBake recipe file and extracts variables and tasks.
    """
    print(f"Parsing recipe: {recipe_path}", flush=True)
    return _parse_file(recipe_path)

def parse_layer_conf(layer_conf_path: str) -> dict:
    """
    Parses layer.conf and extracts variables.
    """
    print(f"Parsing layer conf: {layer_conf_path}", flush=True)
    return _parse_file(layer_conf_path)

def validate_recipe(recipe_path: str, layer_conf_path: str = '') -> dict:
    """
    Validates a recipe for missing fields or bad formats.
    """
    print(f"Validating recipe: {recipe_path}", flush=True)
    recipe_data = parse_recipe(recipe_path)
    result = {
        'valid': True,
        'errors': [],
        'warnings': []
    }

    if not recipe_data:
        result['valid'] = False
        result['errors'].append(f"Failed to parse or empty recipe: {recipe_path}")
        return result

    # Validate LICENSE
    if 'LICENSE' not in recipe_data or not recipe_data['LICENSE'].strip():
        result['valid'] = False
        result['errors'].append("LICENSE field is missing or empty.")

    # Validate SRC_URI format (basic check)
    if 'SRC_URI' in recipe_data:
        src_uris = recipe_data['SRC_URI'].split()
        for uri in src_uris:
            if not any(uri.startswith(scheme) for scheme in ['http://', 'https://', 'git://', 'file://', 'svn://', 'hg://']):
                result['warnings'].append(f"SRC_URI '{uri}' might have an invalid or unknown scheme.")
    
    return result

def build_dependency_graph(recipes_dir: str) -> dict:
    """
    Scans a directory of recipes and builds a networkx directed graph of dependencies.
    """
    print(f"Building dependency graph for recipes in: {recipes_dir}", flush=True)
    graph = nx.DiGraph()
    
    recipe_files = glob.glob(os.path.join(recipes_dir, '**', '*.bb'), recursive=True)
    
    # Map recipe names to parsed data
    recipes_map = {}
    for filepath in recipe_files:
        recipe_name = os.path.splitext(os.path.basename(filepath))[0]
        # In bitbake, recipe name usually has version appended like name_version.bb
        # For simplicity, split by '_' and take first part as base name
        base_name = recipe_name.split('_')[0]
        
        parsed = parse_recipe(filepath)
        recipes_map[base_name] = parsed
        graph.add_node(base_name)

    # Add edges for DEPENDS
    for base_name, parsed in recipes_map.items():
        if 'DEPENDS' in parsed:
            depends = parsed['DEPENDS'].split()
            for dep in depends:
                # Remove version requirements if present
                clean_dep = dep.split('(')[0].strip()
                if clean_dep:
                    graph.add_edge(base_name, clean_dep)

    # Detect cycles
    try:
        cycles = list(nx.simple_cycles(graph))
    except nx.NetworkXNotImplemented:
        cycles = []
    
    stats = {
        'num_recipes': graph.number_of_nodes(),
        'num_dependencies': graph.number_of_edges(),
        'cycles_detected': len(cycles) > 0,
        'cycles': cycles
    }

    return stats
