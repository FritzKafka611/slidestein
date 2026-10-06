"""SlideStein CLI.

Commands
--------
generate    Generate a single consulting slide from a natural-language request.
index       Index a directory of PPTX templates into the slide library.
status      Show library statistics.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="slidestein",
    help="AI consulting slide generator — one slide at a time.",
    add_completion=False,
)
console = Console()


@app.command()
def generate(
    request: str = typer.Argument(..., help="Describe the slide you need in plain language."),
    output: Path = typer.Option(
        Path("output.pptx"),
        "--output",
        "-o",
        help="Destination path for the generated PPTX.",
    ),
) -> None:
    """Generate a single consulting slide from a natural-language request."""
    from slidestein.config import get_settings
    from slidestein.domain.models import UserRequest
    from slidestein.library.store import SlideLibrary
    from slidestein.pipeline import SlideSteinPipeline
    from slidestein.pptx.stub import StubPPTMasterAdapter

    settings = get_settings()
    console.print(f"[bold cyan]SlideStein[/bold cyan]  generating slide…")
    console.print(f"  Request : {request!r}")
    console.print(f"  Output  : {output}")

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        pipeline = SlideSteinPipeline(
            settings=settings,
            library=library,
            ppt_adapter=StubPPTMasterAdapter(),
        )
        try:
            result = pipeline.run(UserRequest(text=request))
        except NotImplementedError as exc:
            console.print(f"[yellow]Pipeline stage not yet implemented:[/yellow] {exc}")
            raise typer.Exit(1) from exc

    console.print(f"[green]Done.[/green] Slide written to {result.pptx_path}")


@app.command()
def index(
    slides_dir: Path = typer.Argument(..., help="Directory of PPTX template files to index."),
) -> None:
    """Index a directory of PPTX templates into the slide library."""
    from slidestein.config import get_settings
    from slidestein.library.store import SlideLibrary
    from slidestein.pptx.stub import StubPPTMasterAdapter

    if not slides_dir.is_dir():
        console.print(f"[red]Not a directory:[/red] {slides_dir}")
        raise typer.Exit(1)

    settings = get_settings()
    adapter = StubPPTMasterAdapter()
    indexed = 0
    errors = 0

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        for pptx_path in sorted(slides_dir.glob("**/*.pptx")):
            try:
                metadata = adapter.introspect_template(pptx_path)
                library.index_slide(metadata)
                console.print(f"  [green]✓[/green] {pptx_path.name}  [{metadata.slide_id}]")
                indexed += 1
            except Exception as exc:
                console.print(f"  [red]✗[/red] {pptx_path.name}  {exc}")
                errors += 1

    console.print(f"\nIndexed {indexed} slide(s), {errors} error(s).")
    if errors:
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show slide library statistics."""
    from slidestein.config import get_settings
    from slidestein.library.store import SlideLibrary

    settings = get_settings()

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        total = library.count()
        slides = library.list_all()

    table = Table(title="SlideStein Library")
    table.add_column("Slide ID", style="cyan")
    table.add_column("Archetype")
    table.add_column("Description")
    table.add_column("Slots", justify="right")

    for s in slides:
        table.add_row(
            s.slide_id,
            s.archetype.value,
            s.description[:60],
            str(len(s.content_slots)),
        )

    console.print(table)
    console.print(f"\nTotal: [bold]{total}[/bold] slide(s)")
