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

    # Entry points
    functions: list[DetectedFunction] = field(default_factory=list)
    suggested_entry: Optional[DetectedFunction] = None

    # Agent.json
    has_agent_json: bool = False
    agent_json_path: Optional[str] = None

    # Files
    python_files: list[str] = field(default_factory=list)
    total_files: int = 0

    # Errors
    errors: list[str] = field(default_factory=list)


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


def read_dependencies(repo_path: str) -> tuple[list[str], dict]:
    """
    Read Python dependencies from requirements.txt.
    Returns (list_of_deps, metadata_dict).
    """
    path = Path(repo_path)
    deps = []
    meta = {
        "has_requirements_txt": False,
        "has_setup_py": False,
        "has_pyproject_toml": False,
    }

    # requirements.txt
    req_file = path / "requirements.txt"
    if req_file.exists():
        meta["has_requirements_txt"] = True
        for line in req_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                # Strip version specifiers for display
                pkg = re.split(r"[>=<!\[]", line)[0].strip()
                if pkg:
                    deps.append(pkg)

    # Check for other packaging files
    meta["has_setup_py"] = (path / "setup.py").exists()
    meta["has_pyproject_toml"] = (path / "pyproject.toml").exists()

    return deps, meta


def extract_functions(filepath: str, repo_path: str, parse_errors: list[str] | None = None) -> list[DetectedFunction]:
    """
    Parse a Python file and extract top-level function definitions.
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

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Skip private/dunder functions
            if node.name.startswith("_"):
                continue

            # Get arguments (skip 'self')
            args = []
            for arg in node.args.args:
                if arg.arg != "self":
                    args.append(arg.arg)

            # Check if it has a return statement
            has_return = any(
                isinstance(child, ast.Return) and child.value is not None
                for child in ast.walk(node)
            )

            # Get docstring
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

    return functions


def score_entry_point(func: DetectedFunction, filename: str) -> int:
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

    # Function name signals
    name = func.name.lower()
    if name in ("main", "run", "process", "convert", "execute", "handle"):
        score += 10
    if name.startswith(("get_", "fetch_", "create_", "generate_", "build_")):
        score += 5

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


def suggest_entry_point(functions: list[DetectedFunction]) -> Optional[DetectedFunction]:
    """Pick the most likely entry point from detected functions."""
    if not functions:
        return None

    scored = [
        (func, score_entry_point(func, func.file))
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

    # Step 3: Read dependencies
    analysis.dependencies, dep_meta = read_dependencies(local_path)
    analysis.has_requirements_txt = dep_meta["has_requirements_txt"]
    analysis.has_setup_py = dep_meta["has_setup_py"]
    analysis.has_pyproject_toml = dep_meta["has_pyproject_toml"]

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
    analysis.suggested_entry = suggest_entry_point(all_functions)

    # Step 6: Check for agent.json
    analysis.has_agent_json, analysis.agent_json_path = check_agent_json(local_path)

    # Step 7: Check for dangerous imports (warnings only)
    dangerous = check_dangerous_imports(local_path)
    if dangerous:
        for warning in dangerous:
            analysis.errors.append(f"Security: {warning}")

    return analysis
