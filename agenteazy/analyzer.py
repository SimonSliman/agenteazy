"""
Repo Analyzer - The brain of AgentEazy (Day 1)

Clones a GitHub repo, detects:
- Language (Python only for v0.1)
- Entry point (main function)
- Dependencies (requirements.txt)
- Whether agent.json already exists
"""

import os
import re
import ast
import shutil
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from git import Repo, GitCommandError


@dataclass
class DetectedFunction:
    """A function detected as a potential agent entry point."""
    name: str
    file: str
    args: list[str] = field(default_factory=list)
    has_return: bool = False
    docstring: Optional[str] = None
    line_number: int = 0
    class_name: Optional[str] = None


@dataclass
class RepoAnalysis:
    """Complete analysis of a GitHub repo."""
    # Basics
    repo_url: str
    repo_name: str
    local_path: str

    # Detection
    language: Optional[str] = None
    python_version: Optional[str] = None

    # Dependencies
    dependencies: list[str] = field(default_factory=list)
    has_requirements_txt: bool = False
    has_setup_py: bool = False
    has_pyproject_toml: bool = False
    dep_source: Optional[str] = None

    # Entry points
    functions: list[DetectedFunction] = field(default_factory=list)
    suggested_entry: Optional[DetectedFunction] = None

    # Agent.json
    has_agent_json: bool = False
    agent_json_path: Optional[str] = None

    # Files
    python_files: list[str] = field(default_factory=list)
    total_files: int = 0

    # Package layout
    package_layout: str = "flat"
    python_root: str = "."

    # Errors
    errors: list[str] = field(default_factory=list)


def detect_package_layout(repo_path: str) -> dict:
    """
    Detect the Python package layout of a repo.

    Returns:
        {
            "layout": "flat" | "src" | "package",
            "python_root": "." | "src" | etc.,
            "packages": ["mypackage", ...]
        }

    Detection logic:
    - "src": repo has src/ dir containing __init__.py or Python files in subdirs
    - "package": repo root has __init__.py (the repo itself is a package)
    - "flat": everything else (loose .py files at root)
    """
    path = Path(repo_path)
    packages = []

    # Check for src/ layout
    src_dir = path / "src"
    if src_dir.is_dir():
        # Look for packages inside src/
        for child in src_dir.iterdir():
            if child.is_dir() and (child / "__init__.py").exists():
                packages.append(child.name)
        if packages:
            return {"layout": "src", "python_root": "src", "packages": packages}
        # Check for loose Python files in src/
        if list(src_dir.glob("*.py")):
            return {"layout": "src", "python_root": "src", "packages": []}

    # Check for root package layout
    if (path / "__init__.py").exists():
        packages.append(path.name)
        return {"layout": "package", "python_root": ".", "packages": packages}

    # Flat layout — collect any top-level dirs with __init__.py
    for child in path.iterdir():
        if child.is_dir() and (child / "__init__.py").exists():
            if child.name not in (".git", "__pycache__", ".tox", ".venv", "venv"):
                packages.append(child.name)

    return {"layout": "flat", "python_root": ".", "packages": packages}


def parse_github_url(url: str) -> tuple[str, str]:
    """
    Parse a GitHub URL or shorthand into (clone_url, repo_name).

    Accepts:
      - github.com/user/repo
      - https://github.com/user/repo
      - https://github.com/user/repo.git
      - user/repo
    """
    url = url.strip().rstrip("/")

    # Remove .git suffix
    if url.endswith(".git"):
        url = url[:-4]

    # Handle shorthand: user/repo
    if re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", url):
        repo_name = url.split("/")[-1]
        return f"https://github.com/{url}.git", repo_name

    # Handle github.com/user/repo (no scheme)
    if url.startswith("github.com/"):
        repo_name = url.split("/")[-1]
        return f"https://{url}.git", repo_name

    # Handle full URL
    if "github.com" in url:
        repo_name = url.split("/")[-1]
        clone_url = url if url.startswith("https://") else f"https://{url}"
        return f"{clone_url}.git", repo_name

    raise ValueError(
        f"Cannot parse '{url}'. Use format: github.com/user/repo or user/repo"
    )


def clone_repo(url: str, target_dir: Optional[str] = None) -> tuple[str, str]:
    """
    Clone a GitHub repo to a temporary directory.
    Returns (local_path, repo_name).
    """
    clone_url, repo_name = parse_github_url(url)

    if target_dir is None:
        target_dir = os.path.join(tempfile.gettempdir(), "agenteazy", repo_name)

    # Clean up if exists
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)

    try:
        Repo.clone_from(clone_url, target_dir, depth=1)
    except GitCommandError as e:
        stderr = str(e)
        if "not found" in stderr or "404" in stderr:
            raise RuntimeError(
                f"Repository not found: {clone_url}\n"
                f"Check the URL and ensure the repo is public (or you have access)."
            ) from None
        if "Authentication failed" in stderr or "403" in stderr:
            raise RuntimeError(
                f"Authentication failed for: {clone_url}\n"
                f"This may be a private repo. Ensure your git credentials are configured."
            ) from None
        if "Could not resolve host" in stderr or "unable to access" in stderr.lower():
            raise RuntimeError(
                f"Network error cloning {clone_url}\n"
                f"Check your internet connection and try again."
            ) from None
        raise RuntimeError(f"Git clone failed: {stderr}") from None

    return target_dir, repo_name


def detect_language(repo_path: str) -> Optional[str]:
    """Detect the primary language of the repo."""
    path = Path(repo_path)

    py_files = list(path.rglob("*.py"))
    js_files = list(path.rglob("*.js")) + list(path.rglob("*.ts"))

    # For v0.1, we only support Python
    if py_files:
        return "python"
    if js_files:
        return "javascript"  # Detected but not yet supported

    return None


def _read_requirements_txt(path: Path) -> list[str]:
    """Read dependencies from requirements.txt, keeping full version specifiers."""
    req_file = path / "requirements.txt"
    if not req_file.exists():
        return []
    deps = []
    for line in req_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            if line:
                deps.append(line)
    return deps


def _read_pyproject_toml(path: Path) -> list[str]:
    """Read dependencies from pyproject.toml (PEP 621 or Poetry format)."""
    toml_file = path / "pyproject.toml"
    if not toml_file.exists():
        return []

    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib
        except ModuleNotFoundError:
            return []

    try:
        with open(toml_file, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []

    # PEP 621: [project].dependencies
    pep621_deps = data.get("project", {}).get("dependencies", [])
    if pep621_deps and isinstance(pep621_deps, list):
        return [str(d) for d in pep621_deps]

    # Poetry: [tool.poetry.dependencies]
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    if poetry_deps and isinstance(poetry_deps, dict):
        deps = []
        for pkg, version in poetry_deps.items():
            if pkg.lower() == "python":
                continue
            if isinstance(version, str):
                # Convert Poetry version spec to pip format
                ver = version.strip()
                if ver.startswith("^"):
                    deps.append(f"{pkg}>={ver[1:]}")
                elif ver.startswith("~"):
                    deps.append(f"{pkg}>={ver[1:]}")
                elif ver == "*":
                    deps.append(pkg)
                else:
                    deps.append(f"{pkg}{ver}" if ver[0] in "><=!" else f"{pkg}=={ver}")
            elif isinstance(version, dict):
                v = version.get("version", "")
                if v:
                    if v.startswith("^"):
                        deps.append(f"{pkg}>={v[1:]}")
                    elif v.startswith("~"):
                        deps.append(f"{pkg}>={v[1:]}")
                    else:
                        deps.append(f"{pkg}{v}" if v[0] in "><=!" else f"{pkg}=={v}")
                else:
                    deps.append(pkg)
            else:
                deps.append(pkg)
        return deps

    return []


def _read_setup_py(path: Path) -> list[str]:
    """Read dependencies from setup.py via AST (no code execution)."""
    setup_file = path / "setup.py"
    if not setup_file.exists():
        return []

    try:
        source = setup_file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    def _extract_list_of_strings(node) -> list[str] | None:
        """Extract a list of string constants from an AST node."""
        if isinstance(node, ast.List):
            result = []
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    result.append(elt.value)
            return result if result else None
        return None

    # Walk the AST to find setup() call
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Check if the function being called is "setup"
        func = node.func
        if isinstance(func, ast.Name) and func.id == "setup":
            pass
        elif isinstance(func, ast.Attribute) and func.attr == "setup":
            pass
        else:
            continue

        # Look for install_requires keyword
        for kw in node.keywords:
            if kw.arg != "install_requires":
                continue

            # Case 1: Direct list literal
            result = _extract_list_of_strings(kw.value)
            if result is not None:
                return result

            # Case 2: Variable reference — search module body for assignment
            if isinstance(kw.value, ast.Name):
                var_name = kw.value.id
                for stmt in tree.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name) and target.id == var_name:
                                result = _extract_list_of_strings(stmt.value)
                                if result is not None:
                                    return result

    return []


def read_dependencies(repo_path: str) -> tuple[list[str], dict]:
    """
    Read Python dependencies from requirements.txt, pyproject.toml, or setup.py.
    Returns (list_of_deps, metadata_dict).

    Fallback priority: requirements.txt -> pyproject.toml -> setup.py.
    Uses the first source that returns deps (no merging across sources).
    Full version specifiers are preserved.
    """
    path = Path(repo_path)
    meta = {
        "has_requirements_txt": (path / "requirements.txt").exists(),
        "has_setup_py": (path / "setup.py").exists(),
        "has_pyproject_toml": (path / "pyproject.toml").exists(),
        "dep_source": None,
    }

    # Try requirements.txt first
    if meta["has_requirements_txt"]:
        deps = _read_requirements_txt(path)
        if deps:
            meta["dep_source"] = "requirements.txt"
            return deps, meta

    # Try pyproject.toml
    if meta["has_pyproject_toml"]:
        deps = _read_pyproject_toml(path)
        if deps:
            meta["dep_source"] = "pyproject.toml"
            return deps, meta

    # Try setup.py
    if meta["has_setup_py"]:
        deps = _read_setup_py(path)
        if deps:
            meta["dep_source"] = "setup.py"
            return deps, meta

    return [], meta


_MAIN_API_NAMES = {
    "parse", "detect", "convert", "format", "clean", "validate",
    "transform", "analyze", "extract", "encode", "decode",
    "compress", "decompress", "encrypt", "decrypt", "translate",
    "slugify", "markdown", "beautify", "fix", "sanitize",
    "tokenize", "classify", "predict", "generate", "render",
    "compile", "evaluate", "serialize", "deserialize",
    "emojize", "demojize", "humanize", "pluralize", "singularize",
    "cut", "get", "request", "send", "load", "dump",
}

_INTERESTING_METHODS = {
    "__call__", "run", "process", "predict", "execute",
    "handle", "generate", "analyze", "transform", "convert", "forward",
    "__init__",
} | _MAIN_API_NAMES


def extract_functions(filepath: str, repo_path: str, parse_errors: list[str] | None = None) -> list[DetectedFunction]:
    """
    Parse a Python file and extract top-level functions and class methods.
    Uses AST parsing - safe, no code execution.

    If parse_errors is provided, syntax errors are appended to it instead of silently ignored.
    """
    functions = []
    try:
        source = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except SyntaxError as e:
        rel = os.path.relpath(filepath, repo_path)
        if parse_errors is not None:
            parse_errors.append(f"Syntax error in {rel}: {e.msg} (line {e.lineno})")
        return functions
    except UnicodeDecodeError:
        rel = os.path.relpath(filepath, repo_path)
        if parse_errors is not None:
            parse_errors.append(f"Could not read {rel}: encoding error (skipped)")
        return functions

    rel_path = os.path.relpath(filepath, repo_path)

    # First pass: collect TRUE top-level functions (direct children of module body only)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            # Skip private/dunder functions
            if node.name.startswith("_"):
                continue

            args = [arg.arg for arg in node.args.args if arg.arg not in ("self", "cls")]

            has_return = any(
                isinstance(child, ast.Return) and child.value is not None
                for child in ast.walk(node)
            )

            docstring = ast.get_docstring(node)

            functions.append(
                DetectedFunction(
                    name=node.name,
                    file=rel_path,
                    args=args,
                    has_return=has_return,
                    docstring=docstring,
                    line_number=node.lineno,
                )
            )

    # Second pass: walk ClassDef nodes for interesting methods
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        class_name = node.name
        # Skip private classes and test classes
        if class_name.startswith("_") or class_name.startswith("Test"):
            continue

        interesting_methods = []
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if item.name not in _INTERESTING_METHODS:
                continue

            args = [arg.arg for arg in item.args.args if arg.arg not in ("self", "cls")]

            has_return = any(
                isinstance(child, ast.Return) and child.value is not None
                for child in ast.walk(item)
            )

            docstring = ast.get_docstring(item)

            interesting_methods.append(
                DetectedFunction(
                    name=item.name,
                    file=rel_path,
                    args=args,
                    has_return=has_return,
                    docstring=docstring,
                    line_number=item.lineno,
                    class_name=class_name,
                )
            )

        # Only include __init__ if it's the sole interesting method
        if len(interesting_methods) > 1:
            interesting_methods = [m for m in interesting_methods if m.name != "__init__"]

        functions.extend(interesting_methods)

    # Detect Flask/FastAPI web apps
    _detect_web_framework(tree, rel_path, parse_errors)

    return functions


def _detect_web_framework(tree: ast.Module, rel_path: str, parse_errors: list[str] | None) -> None:
    """Detect Flask/FastAPI app instantiation and warn."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name in ("Flask", "FastAPI"):
            if parse_errors is not None:
                parse_errors.append(
                    f"This repo is a web application ({name}). "
                    f"It already has API endpoints — wrapping may cause conflicts. "
                    f"Consider using --entry to specify a utility function instead."
                )
            return


def _get_init_exports(repo_path: str, package_dir: str) -> set[str]:
    """Parse __init__.py to find explicitly exported function names."""
    init_path = os.path.join(repo_path, package_dir, "__init__.py")
    if not os.path.isfile(init_path):
        return set()

    try:
        source = Path(init_path).read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return set()

    exports = set()

    for node in ast.walk(tree):
        # from .module import func_name
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                exports.add(alias.asname or alias.name)
        # __all__ = ["func1", "func2"]
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                exports.add(elt.value)

    return exports


def score_entry_point(func: DetectedFunction, filename: str, init_exports: set[str] | None = None) -> int:
    """
    Score a function as a potential entry point.
    Higher = more likely to be the main function.
    """
    score = 0

    # Filename signals
    basename = os.path.basename(filename).replace(".py", "").lower()
    if basename in ("main", "app", "run", "cli", "server"):
        score += 10
    if basename == "convert" or basename == "process":
        score += 8

    # Signal 1: __init__.py bonus — functions defined here ARE the public API
    # Top-level __init__.py gets full bonus; sub-package __init__.py gets less
    if basename == "__init__":
        depth_of_init = filename.count("/")
        if depth_of_init <= 1:
            score += 25  # e.g. jieba/__init__.py
        else:
            score += 10  # e.g. jieba/posseg/__init__.py

    # Function name signals
    name = func.name.lower()
    if name in ("main", "run", "process", "convert", "execute", "handle"):
        score += 10
    if name.startswith(("get_", "fetch_", "create_", "generate_", "build_")):
        score += 5

    # Signal 2: Package name match
    parts = os.path.dirname(filename).replace("\\", "/").split("/")
    pkg_name = parts[-1].lower() if parts and parts[-1] else ""
    if pkg_name and (name in pkg_name or pkg_name in name):
        score += 20
    # Also match common patterns: "python-X" package → function "X"
    pkg_clean = pkg_name.replace("python-", "").replace("python_", "").replace("-", "").replace("_", "")
    if pkg_clean and (name == pkg_clean or name.startswith(pkg_clean) or pkg_clean.startswith(name)):
        score += 20

    # Signal 3: Common main-API function names
    if name in _MAIN_API_NAMES:
        score += 15

    # Signal 4: File depth penalty — deeper files are more internal
    depth = filename.count("/")
    if depth > 1:
        score -= (depth - 1) * 3

    # Signal 5: Internal utility penalty
    if name.startswith("get_") and len(name) > 5:
        score -= 10
    if name.startswith(("_check", "_validate", "_parse", "_build", "_make")):
        score -= 15

    # Signal 6: Exported from __init__.py detection
    if init_exports and func.name in init_exports:
        score += 30

    # Signal 7: Single-arg "main input" functions
    num_args = len(func.args)
    if 1 <= num_args <= 3:
        score += 10
    elif num_args > 5:
        score -= 5

    # Class method scoring
    if func.class_name:
        if name == "__call__":
            score += 8
        if name in ("predict", "process", "run", "execute"):
            score += 6
        # Class name keyword bonuses
        cls_lower = func.class_name.lower()
        for kw in ("model", "predictor", "processor", "handler", "agent", "pipeline", "analyzer"):
            if kw in cls_lower:
                score += 5
                break
        # Penalize __init__ unless it's the only method
        if name == "__init__":
            score -= 5

    # Has arguments = likely a real function (not just a script)
    if func.args:
        score += 3

    # Has return = produces output
    if func.has_return:
        score += 5

    # Has docstring = well-documented
    if func.docstring:
        score += 3

    # Not in test files
    if "test" in func.file.lower():
        score -= 20

    # Not in setup/config files
    if func.file in ("setup.py", "conftest.py"):
        score -= 20

    return score


def suggest_entry_point(functions: list[DetectedFunction], repo_path: str = "") -> Optional[DetectedFunction]:
    """Pick the most likely entry point from detected functions."""
    if not functions:
        return None

    # Find package directory and exports
    # Prefer the package whose name matches the repo name
    init_exports: set[str] = set()
    if repo_path:
        repo_name = os.path.basename(repo_path.rstrip("/")).lower()
        repo_clean = repo_name.replace("python-", "").replace("python_", "").replace("-", "").replace("_", "")

        def _find_best_package(search_dir: str) -> set[str]:
            """Find exports from the best-matching package in search_dir."""
            try:
                candidates = [
                    d for d in os.listdir(search_dir)
                    if os.path.isfile(os.path.join(search_dir, d, "__init__.py"))
                    and not d.startswith(("test", "."))
                ]
            except OSError:
                return set()
            if not candidates:
                return set()
            # Prefer package matching repo name
            d_clean = {d: d.lower().replace("-", "").replace("_", "") for d in candidates}
            for d in candidates:
                if d_clean[d] == repo_clean or d.lower() == repo_name:
                    return _get_init_exports(search_dir, d)
            # Fallback: first non-test package
            return _get_init_exports(search_dir, candidates[0])

        init_exports = _find_best_package(repo_path)
        # Also check src/ layout
        src_dir = os.path.join(repo_path, "src")
        if not init_exports and os.path.isdir(src_dir):
            init_exports = _find_best_package(src_dir)

    scored = [
        (func, score_entry_point(func, func.file, init_exports=init_exports))
        for func in functions
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Only suggest if the top score is reasonable
    if scored[0][1] > 0:
        return scored[0][0]

    # Fallback: just pick the first function in the first file
    return functions[0]


def check_agent_json(repo_path: str) -> tuple[bool, Optional[str]]:
    """Check if the repo already has an agent.json file."""
    path = Path(repo_path)
    agent_json = path / "agent.json"
    if agent_json.exists():
        return True, str(agent_json)
    return False, None


DANGEROUS_PATTERNS = [
    "os.system",
    "subprocess",
    "eval(",
    "exec(",
    "__import__",
    "importlib",
    "ctypes",
    "socket",
]


def check_dangerous_imports(repo_path: str) -> list[str]:
    """Scan all Python files for potentially dangerous imports/calls.

    Returns a list of warning strings describing what was found.
    This does NOT block wrapping — it only produces warnings.
    """
    warnings = []
    path = Path(repo_path)

    for py_file in path.rglob("*.py"):
        if ".git" in str(py_file) or "__pycache__" in str(py_file):
            continue

        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        rel = str(py_file.relative_to(path))

        for pattern in DANGEROUS_PATTERNS:
            for i, line in enumerate(source.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if pattern in line:
                    warnings.append(f"{rel}:{i} — uses '{pattern}'")

    return warnings


def analyze_repo(url: str) -> RepoAnalysis:
    """
    Full analysis pipeline. This is the main function for Day 1.

    Accepts a GitHub URL/shorthand OR a local directory path.

    1. Clone the repo (or use local path)
    2. Detect language
    3. Read dependencies
    4. Find functions
    5. Suggest entry point
    6. Check for agent.json
    """
    # Step 1: Clone or use local path
    if os.path.isdir(url):
        local_path = os.path.abspath(url)
        repo_name = os.path.basename(local_path.rstrip("/"))
        analysis = RepoAnalysis(
            repo_url=url,
            repo_name=repo_name,
            local_path=local_path,
        )
    else:
        try:
            local_path, repo_name = clone_repo(url)
        except Exception as e:
            analysis = RepoAnalysis(
                repo_url=url,
                repo_name=url.split("/")[-1],
                local_path="",
            )
            analysis.errors.append(f"Clone failed: {e}")
            return analysis

        analysis = RepoAnalysis(
            repo_url=url,
            repo_name=repo_name,
            local_path=local_path,
        )

    path = Path(local_path)

    # Check for empty repo
    all_files = list(path.rglob("*"))
    non_git_files = [f for f in all_files if ".git" not in str(f)]
    if not non_git_files:
        analysis.errors.append("Repository is empty — no files found")
        return analysis

    # Step 2: Detect language
    analysis.language = detect_language(local_path)

    if analysis.language != "python":
        if analysis.language:
            analysis.errors.append(
                f"Detected {analysis.language} — only Python is supported in v0.1"
            )
        else:
            analysis.errors.append(
                "No Python files found. AgentEazy v0.1 only supports Python repos."
            )
        return analysis

    # Step 2b: Detect package layout
    layout_info = detect_package_layout(local_path)
    analysis.package_layout = layout_info["layout"]
    analysis.python_root = layout_info["python_root"]

    # Step 3: Read dependencies
    analysis.dependencies, dep_meta = read_dependencies(local_path)
    analysis.has_requirements_txt = dep_meta["has_requirements_txt"]
    analysis.has_setup_py = dep_meta["has_setup_py"]
    analysis.has_pyproject_toml = dep_meta["has_pyproject_toml"]
    analysis.dep_source = dep_meta.get("dep_source")

    # Step 4: Find all Python files and extract functions
    analysis.python_files = [
        str(f.relative_to(path))
        for f in path.rglob("*.py")
        if ".git" not in str(f) and "__pycache__" not in str(f)
    ]
    analysis.total_files = len(all_files)

    parse_errors: list[str] = []
    all_functions = []
    for py_file in analysis.python_files:
        full_path = os.path.join(local_path, py_file)
        funcs = extract_functions(full_path, local_path, parse_errors=parse_errors)
        all_functions.extend(funcs)

    # Report parse errors as warnings
    for err in parse_errors:
        analysis.errors.append(err)

    analysis.functions = all_functions

    if not all_functions:
        analysis.errors.append(
            "No functions found in any Python file. "
            "Check that your code has top-level function definitions."
        )

    # Step 5: Suggest entry point
    analysis.suggested_entry = suggest_entry_point(all_functions, repo_path=local_path)

    # Step 6: Check for agent.json
    analysis.has_agent_json, analysis.agent_json_path = check_agent_json(local_path)

    # Step 7: Check for dangerous imports (warnings only)
    dangerous = check_dangerous_imports(local_path)
    if dangerous:
        for warning in dangerous:
            analysis.errors.append(f"Security: {warning}")

    return analysis
