"""AgentEazy CLI - Turn any GitHub repo into an AI agent in one command."""

import os
import shutil

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agenteazy.analyzer import analyze_repo
from agenteazy.deployer import deploy_local, test_agent
from agenteazy.generator import generate_agent_json, save_agent_json
from agenteazy.wrapper_template import generate_wrapper, validate_wrapper

app = typer.Typer(
    name="agenteazy",
    help="Turn any GitHub repo into an AI agent in one command.",
    add_completion=False,
)
console = Console()


@app.command()
def analyze(repo_url: str = typer.Argument(..., help="GitHub repo URL or user/repo shorthand")):
    """Clone and analyze a GitHub repo, showing detected structure."""
    console.print(f"\n[bold blue]Analyzing[/bold blue] {repo_url}...\n")

    try:
        analysis = analyze_repo(repo_url)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    if analysis.errors:
        for err in analysis.errors:
            console.print(f"[yellow]Warning:[/yellow] {err}")
        if not analysis.language:
            raise typer.Exit(code=1)

    # Summary table
    table = Table(title=f"Analysis: {analysis.repo_name}", show_header=False)
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Language", analysis.language or "unknown")
    table.add_row("Python files", str(len(analysis.python_files)))
    table.add_row("Total files", str(analysis.total_files))
    table.add_row("Dependencies", str(len(analysis.dependencies)))

    if analysis.dependencies:
        table.add_row("Top deps", ", ".join(analysis.dependencies[:8]))

    table.add_row("Functions found", str(len(analysis.functions)))

    if analysis.suggested_entry:
        entry = analysis.suggested_entry
        table.add_row(
            "Suggested entry",
            f"{entry.name}({', '.join(entry.args)}) in {entry.file}",
        )

    table.add_row("Has agent.json", "yes" if analysis.has_agent_json else "no")

    console.print(table)
    console.print()


@app.command()
def wrap(repo_url: str = typer.Argument(..., help="GitHub repo URL or user/repo shorthand")):
    """Analyze a repo, generate agent.json and a FastAPI wrapper."""
    console.print(f"\n[bold blue]Wrapping[/bold blue] {repo_url}...\n")

    # Step 1: Analyze
    console.print("[dim]Step 1/3: Analyzing repo...[/dim]")
    try:
        analysis = analyze_repo(repo_url)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    if analysis.errors:
        for err in analysis.errors:
            console.print(f"[yellow]Warning:[/yellow] {err}")

    if not analysis.suggested_entry:
        console.print("[bold red]Error:[/bold red] No suitable entry point found.")
        raise typer.Exit(code=1)

    # Step 2: Generate agent.json
    console.print("[dim]Step 2/3: Generating agent.json...[/dim]")
    agent_config = generate_agent_json(analysis)

    # Step 3: Generate wrapper
    console.print("[dim]Step 3/3: Generating FastAPI wrapper...[/dim]")
    wrapper_code = generate_wrapper(agent_config, analysis.local_path)

    if not validate_wrapper(wrapper_code):
        console.print("[bold red]Error:[/bold red] Generated wrapper has syntax errors.")
        raise typer.Exit(code=1)

    # Save everything to ./agenteazy-output/{repo_name}/
    output_dir = os.path.join(".", "agenteazy-output", analysis.repo_name)
    os.makedirs(output_dir, exist_ok=True)

    # Save agent.json
    agent_path = save_agent_json(agent_config, output_dir)

    # Save wrapper.py
    wrapper_path = os.path.join(output_dir, "wrapper.py")
    with open(wrapper_path, "w") as f:
        f.write(wrapper_code)

    # Copy repo source into output_dir/repo/
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

    # Print summary
    console.print()
    console.print(Panel.fit(
        f"[bold green]Done![/bold green] Output saved to [cyan]{output_dir}/[/cyan]\n\n"
        f"  agent.json   - Agent configuration\n"
        f"  wrapper.py   - FastAPI server\n"
        f"  requirements.txt - All dependencies\n\n"
        f"[bold]To test locally:[/bold]\n"
        f"  cd {output_dir}\n"
        f"  pip install -r requirements.txt\n"
        f"  python wrapper.py",
        title="AgentEazy",
    ))


@app.command()
def deploy(
    repo_url: str = typer.Argument(..., help="GitHub repo URL, user/repo shorthand, or local path"),
    port: int = typer.Option(8000, "--port", "-p", help="Port for the local server"),
):
    """Analyze, wrap, install deps, and deploy a local agent server."""
    import subprocess as _sp

    console.print(f"\n[bold blue]Deploying[/bold blue] {repo_url}...\n")

    # Step 1: Analyze
    console.print("[dim]Step 1/4: Analyzing repo...[/dim]")
    try:
        analysis = analyze_repo(repo_url)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

    if analysis.errors:
        for err in analysis.errors:
            console.print(f"[yellow]Warning:[/yellow] {err}")

    if not analysis.suggested_entry:
        console.print("[bold red]Error:[/bold red] No suitable entry point found.")
        raise typer.Exit(code=1)

    # Step 2: Generate agent.json + wrapper
    console.print("[dim]Step 2/4: Generating agent.json and wrapper...[/dim]")
    agent_config = generate_agent_json(analysis)
    wrapper_code = generate_wrapper(agent_config, analysis.local_path)

    if not validate_wrapper(wrapper_code):
        console.print("[bold red]Error:[/bold red] Generated wrapper has syntax errors.")
        raise typer.Exit(code=1)

    output_dir = os.path.join(".", "agenteazy-output", analysis.repo_name)
    os.makedirs(output_dir, exist_ok=True)

    save_agent_json(agent_config, output_dir)

    wrapper_path = os.path.join(output_dir, "wrapper.py")
    with open(wrapper_path, "w") as f:
        f.write(wrapper_code)

    reqs_path = os.path.join(output_dir, "requirements.txt")
    wrapper_deps = ["fastapi>=0.100.0", "uvicorn>=0.23.0"]
    all_deps = analysis.dependencies + wrapper_deps
    with open(reqs_path, "w") as f:
        f.write("\n".join(all_deps) + "\n")

    # Step 3: Install deps
    console.print("[dim]Step 3/4: Installing dependencies (fastapi, uvicorn)...[/dim]")
    try:
        _sp.check_call(
            [os.sys.executable, "-m", "pip", "install", "fastapi", "uvicorn"],
            stdout=_sp.DEVNULL,
            stderr=_sp.DEVNULL,
        )
    except _sp.CalledProcessError as e:
        console.print(f"[bold red]Error installing deps:[/bold red] {e}")
        raise typer.Exit(code=1)

    # Step 4: Deploy locally
    console.print("[dim]Step 4/4: Starting local server...[/dim]")
    try:
        deploy_local(output_dir, port=port)
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        pass


@app.command()
def test(
    url: str = typer.Option("http://localhost:8000", "--url", "-u", help="Base URL of running agent"),
):
    """Test all endpoints of a running agent."""
    console.print(f"\n[bold blue]Testing agent at[/bold blue] {url}\n")
    results = test_agent(url)

    all_passed = all(r["passed"] for r in results.values())
    if all_passed:
        console.print("[bold green]All endpoints passed![/bold green]\n")
    else:
        failed = [name for name, r in results.items() if not r["passed"]]
        console.print(f"[bold red]Failed endpoints:[/bold red] {', '.join(failed)}\n")
        raise typer.Exit(code=1)


@app.command()
def search(query: str = typer.Argument(..., help="Search query")):
    """Search for existing wrapped agents."""
    console.print("\n[bold yellow]Search:[/bold yellow] coming soon\n")


if __name__ == "__main__":
    app()
