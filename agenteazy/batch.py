"""Batch deployer — process multiple repos with graceful failure handling."""

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from rich.console import Console
from rich.table import Table

console = Console()


class BatchStatus(Enum):
    SUCCESS = "success"
    ANALYZE_FAILED = "analyze_failed"
    WRAP_FAILED = "wrap_failed"
    DEPLOY_FAILED = "deploy_failed"
    SKIPPED = "skipped"


@dataclass
class BatchResult:
    repo_url: str
    repo_name: str
    status: BatchStatus
    entry_point: Optional[str] = None
    deploy_url: Optional[str] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class BatchReport:
    results: list[BatchResult] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def total(self):
        return len(self.results)

    @property
    def succeeded(self):
        return sum(1 for r in self.results if r.status == BatchStatus.SUCCESS)

    @property
    def failed(self):
        return sum(1 for r in self.results if r.status not in (BatchStatus.SUCCESS, BatchStatus.SKIPPED))

    @property
    def skipped(self):
        return sum(1 for r in self.results if r.status == BatchStatus.SKIPPED)


def parse_repos_file(filepath: str) -> list[str]:
    """Parse a repos file: one GitHub URL per line, # comments, blank lines ignored."""
    repos = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            repos.append(line)
    return repos


def load_entry_overrides(filepath: str) -> dict:
    """Load entry overrides from a JSON file."""
    with open(filepath, "r") as f:
        return json.load(f)


def _extract_repo_name(url: str) -> str:
    """Extract repo name from a GitHub URL or user/repo shorthand."""
    url = url.rstrip("/")
    return url.split("/")[-1].replace(".git", "")


def batch_process(
    repos: list[str],
    mode: str = "full",       # "dry-run", "wrap-only", or "full"
    price: int = 0,
    output_base: str = "./agenteazy-output",
    max_consecutive_failures: int = 10,
    skip_existing: bool = False,
    entry_overrides: dict = None,  # repo_name -> "file:function"
) -> BatchReport:
    """Process multiple repos with graceful failure handling.

    Each repo is wrapped in a try/except so no single failure crashes the batch.
    """
    from agenteazy.analyzer import analyze_repo
    from agenteazy.generator import generate_agent_json, save_agent_json
    from agenteazy.wrapper_template import generate_wrapper, validate_wrapper

    if entry_overrides is None:
        entry_overrides = {}

    report = BatchReport(start_time=time.time())
    consecutive_failures = 0

    os.makedirs(output_base, exist_ok=True)

    for i, repo_url in enumerate(repos):
        repo_name = _extract_repo_name(repo_url)
        output_dir = os.path.join(output_base, repo_name)
        start = time.time()

        # Show progress
        console.print(f"\n[dim][{i + 1}/{len(repos)}][/dim] Processing: [bold]{repo_url}[/bold]")

        try:
            # 1. Skip existing if requested
            if skip_existing and os.path.isdir(output_dir):
                result = BatchResult(
                    repo_url=repo_url,
                    repo_name=repo_name,
                    status=BatchStatus.SKIPPED,
                    duration_seconds=time.time() - start,
                )
                report.results.append(result)
                consecutive_failures = 0
                _print_result_line(result)
                continue

            # 2. Analyze
            try:
                analysis = analyze_repo(repo_url)
            except Exception as e:
                result = BatchResult(
                    repo_url=repo_url,
                    repo_name=repo_name,
                    status=BatchStatus.ANALYZE_FAILED,
                    error=str(e),
                    duration_seconds=time.time() - start,
                )
                report.results.append(result)
                consecutive_failures += 1
                _print_result_line(result)
                if consecutive_failures >= max_consecutive_failures:
                    console.print(f"\n[bold red]Aborting:[/bold red] {max_consecutive_failures} consecutive failures reached.")
                    break
                continue

            # Check for entry point
            if not analysis.suggested_entry:
                # Check overrides before giving up
                if repo_name not in entry_overrides:
                    result = BatchResult(
                        repo_url=repo_url,
                        repo_name=repo_name,
                        status=BatchStatus.ANALYZE_FAILED,
                        error="No entry point found",
                        duration_seconds=time.time() - start,
                    )
                    report.results.append(result)
                    consecutive_failures += 1
                    _print_result_line(result)
                    if consecutive_failures >= max_consecutive_failures:
                        console.print(f"\n[bold red]Aborting:[/bold red] {max_consecutive_failures} consecutive failures reached.")
                        break
                    continue

            # 3. Apply entry overrides
            if repo_name in entry_overrides:
                from agenteazy.cli import _parse_entry_override
                try:
                    override = _parse_entry_override(entry_overrides[repo_name], analysis.local_path)
                    analysis.suggested_entry = override
                except Exception:
                    pass  # Fall back to auto-detected

            entry = analysis.suggested_entry
            entry_desc = f"{entry.file}:{entry.class_name + '.' if entry.class_name else ''}{entry.name}({', '.join(entry.args)})" if entry else "none"

            # 4. Dry-run: just report findings
            if mode == "dry-run":
                result = BatchResult(
                    repo_url=repo_url,
                    repo_name=repo_name,
                    status=BatchStatus.SUCCESS,
                    entry_point=entry_desc,
                    duration_seconds=time.time() - start,
                )
                report.results.append(result)
                consecutive_failures = 0
                _print_result_line(result)
                continue

            # 5. Generate + wrap
            try:
                os.makedirs(output_dir, exist_ok=True)
                agent_config = generate_agent_json(analysis, output_dir=output_dir)

                if price and price > 0:
                    agent_config["pricing"] = {"model": "per_call", "credits_per_call": price}

                wrapper_code = generate_wrapper(agent_config, analysis.local_path)
                if not validate_wrapper(wrapper_code):
                    raise ValueError("Generated wrapper has syntax errors")

                save_agent_json(agent_config, output_dir)

                wrapper_path = os.path.join(output_dir, "wrapper.py")
                with open(wrapper_path, "w") as f:
                    f.write(wrapper_code)

                # Copy repo source
                repo_dest = os.path.join(output_dir, "repo")
                if os.path.exists(repo_dest):
                    shutil.rmtree(repo_dest)
                shutil.copytree(analysis.local_path, repo_dest, dirs_exist_ok=True)

                # Save requirements.txt
                reqs_path = os.path.join(output_dir, "requirements.txt")
                wrapper_deps = ["fastapi>=0.100.0", "uvicorn>=0.23.0"]
                all_deps = analysis.dependencies + wrapper_deps
                with open(reqs_path, "w") as f:
                    f.write("\n".join(all_deps) + "\n")
            except Exception as e:
                result = BatchResult(
                    repo_url=repo_url,
                    repo_name=repo_name,
                    status=BatchStatus.WRAP_FAILED,
                    error=str(e),
                    duration_seconds=time.time() - start,
                )
                report.results.append(result)
                consecutive_failures += 1
                _print_result_line(result)
                if consecutive_failures >= max_consecutive_failures:
                    console.print(f"\n[bold red]Aborting:[/bold red] {max_consecutive_failures} consecutive failures reached.")
                    break
                continue

            # 6. Wrap-only mode: done
            if mode == "wrap-only":
                result = BatchResult(
                    repo_url=repo_url,
                    repo_name=repo_name,
                    status=BatchStatus.SUCCESS,
                    entry_point=entry_desc,
                    duration_seconds=time.time() - start,
                )
                report.results.append(result)
                consecutive_failures = 0
                _print_result_line(result)
                continue

            # 7. Deploy (full mode)
            try:
                from agenteazy.config import get_gateway_url
                from agenteazy.modal_deployer import upload_to_volume

                gateway_url = get_gateway_url()
                if not gateway_url:
                    raise RuntimeError("No gateway URL configured. Deploy gateway first.")
                deploy_url = upload_to_volume(output_dir, analysis.repo_name, gateway_url)
            except Exception as e:
                result = BatchResult(
                    repo_url=repo_url,
                    repo_name=repo_name,
                    status=BatchStatus.DEPLOY_FAILED,
                    entry_point=entry_desc,
                    error=str(e),
                    duration_seconds=time.time() - start,
                )
                report.results.append(result)
                consecutive_failures += 1
                _print_result_line(result)
                if consecutive_failures >= max_consecutive_failures:
                    console.print(f"\n[bold red]Aborting:[/bold red] {max_consecutive_failures} consecutive failures reached.")
                    break
                continue

            # 8. Register with registry (failure is non-fatal)
            try:
                from agenteazy.config import get_registry_url
                from agenteazy.cli import _register_with_registry

                registry_url = get_registry_url()
                if registry_url:
                    _register_with_registry(registry_url, agent_config, deploy_url, analysis)
            except Exception:
                pass  # Registry failure is non-fatal

            result = BatchResult(
                repo_url=repo_url,
                repo_name=repo_name,
                status=BatchStatus.SUCCESS,
                entry_point=entry_desc,
                deploy_url=deploy_url,
                duration_seconds=time.time() - start,
            )
            report.results.append(result)
            consecutive_failures = 0
            _print_result_line(result)

        except KeyboardInterrupt:
            result = BatchResult(
                repo_url=repo_url,
                repo_name=repo_name,
                status=BatchStatus.ANALYZE_FAILED,
                error="Interrupted by user",
                duration_seconds=time.time() - start,
            )
            report.results.append(result)
            console.print("\n[bold yellow]Interrupted by user. Saving report...[/bold yellow]")
            break
        except Exception as e:
            result = BatchResult(
                repo_url=repo_url,
                repo_name=repo_name,
                status=BatchStatus.ANALYZE_FAILED,
                error=str(e),
                duration_seconds=time.time() - start,
            )
            report.results.append(result)
            consecutive_failures += 1
            _print_result_line(result)
            if consecutive_failures >= max_consecutive_failures:
                console.print(f"\n[bold red]Aborting:[/bold red] {max_consecutive_failures} consecutive failures reached.")
                break

    report.end_time = time.time()
    return report


def _print_result_line(result: BatchResult) -> None:
    """Print a single result line with status icon."""
    duration = f"{result.duration_seconds:.1f}s"
    if result.status == BatchStatus.SUCCESS:
        detail = result.entry_point or ""
        console.print(f"  [green]\u2713[/green] {result.repo_url} \u2192 {result.repo_name} ({detail}) {duration}")
    elif result.status == BatchStatus.SKIPPED:
        console.print(f"  [dim]\u2298[/dim] {result.repo_url} \u2192 Skipped (output exists) {duration}")
    else:
        error = result.error or result.status.value
        console.print(f"  [red]\u2717[/red] {result.repo_url} \u2192 {error} {duration}")


def save_batch_report(report: BatchReport, output_base: str, mode: str) -> str:
    """Save the batch report as JSON."""
    os.makedirs(output_base, exist_ok=True)
    report_path = os.path.join(output_base, "_batch-report.json")

    duration = report.end_time - report.start_time
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "total": report.total,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "skipped": report.skipped,
        "duration_seconds": round(duration, 1),
        "results": [],
    }
    for r in report.results:
        entry = {
            "repo_url": r.repo_url,
            "repo_name": r.repo_name,
            "status": r.status.value,
            "duration_seconds": round(r.duration_seconds, 1),
        }
        if r.entry_point:
            entry["entry_point"] = r.entry_point
        if r.deploy_url:
            entry["deploy_url"] = r.deploy_url
        if r.error:
            entry["error"] = r.error
        data["results"].append(entry)

    with open(report_path, "w") as f:
        json.dump(data, f, indent=2)

    return report_path


def print_batch_summary(report: BatchReport, output_base: str, report_path: str) -> None:
    """Print the final batch summary."""
    duration = report.end_time - report.start_time
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    duration_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

    console.print()
    console.print("[bold]\u2501\u2501\u2501 Batch Deploy Complete \u2501\u2501\u2501[/bold]")
    console.print(
        f"Total: {report.total} | "
        f"[green]Success: {report.succeeded}[/green] | "
        f"[red]Failed: {report.failed}[/red] | "
        f"[dim]Skipped: {report.skipped}[/dim]"
    )
    console.print(f"Duration: {duration_str}")

    # Show failed repos
    failed = [r for r in report.results if r.status not in (BatchStatus.SUCCESS, BatchStatus.SKIPPED)]
    if failed:
        console.print("\n[bold red]Failed repos:[/bold red]")
        for r in failed:
            console.print(f"  {r.repo_url} \u2014 {r.error or r.status.value}")

    console.print(f"\nOutput: {output_base}/")
    console.print(f"Report: {report_path}")
    console.print()


def batch_analyze(repos: list[str], output_base: str = "./agenteazy-output") -> None:
    """Analyze multiple repos without wrapping. Shows a summary table and saves JSON."""
    from agenteazy.analyzer import analyze_repo

    os.makedirs(output_base, exist_ok=True)

    table = Table(title="Batch Analysis")
    table.add_column("Repo", style="bold cyan")
    table.add_column("Language")
    table.add_column("Files", justify="right")
    table.add_column("Deps", justify="right")
    table.add_column("Entry Point")
    table.add_column("Wrappable?")

    results = []

    for i, repo_url in enumerate(repos):
        repo_name = _extract_repo_name(repo_url)
        console.print(f"[dim][{i + 1}/{len(repos)}] Analyzing {repo_url}...[/dim]")

        entry_data = {
            "repo_url": repo_url,
            "repo_name": repo_name,
        }

        try:
            analysis = analyze_repo(repo_url)
            lang = analysis.language or "unknown"
            n_files = len(analysis.python_files)
            n_deps = len(analysis.dependencies)

            if analysis.suggested_entry:
                e = analysis.suggested_entry
                entry_str = f"{e.name}({', '.join(e.args)})"
                wrappable = "[green]\u2713[/green]"
                wrappable_bool = True
            elif lang.lower() != "python":
                entry_str = "n/a"
                wrappable = f"[red]\u2717 (not python)[/red]"
                wrappable_bool = False
            else:
                entry_str = "none found"
                wrappable = f"[red]\u2717 (no entry)[/red]"
                wrappable_bool = False

            table.add_row(repo_url, lang, str(n_files), str(n_deps), entry_str, wrappable)
            entry_data.update({
                "language": lang,
                "python_files": n_files,
                "dependencies": n_deps,
                "entry_point": entry_str,
                "wrappable": wrappable_bool,
            })
        except Exception as e:
            table.add_row(repo_url, "?", "?", "?", str(e), "[red]\u2717 (error)[/red]")
            entry_data.update({
                "language": "unknown",
                "error": str(e),
                "wrappable": False,
            })

        results.append(entry_data)

    console.print()
    console.print(table)
    console.print()

    # Save analysis report
    report_path = os.path.join(output_base, "_batch-analysis.json")
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": len(results),
            "results": results,
        }, f, indent=2)

    console.print(f"[dim]Analysis saved to: {report_path}[/dim]\n")
