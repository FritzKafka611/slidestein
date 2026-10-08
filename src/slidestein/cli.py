"""SlideStein CLI.

Commands
--------
generate    Generate a single consulting slide from a natural-language request.
index       Ingest a PPTX deck into the slide library (one record per slide).
status      Show library statistics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

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
    console.print("[bold cyan]SlideStein[/bold cyan]  generating slide…")
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
    source: Path = typer.Argument(..., help="Path to a .pptx file to ingest."),
    no_preview: bool = typer.Option(
        False,
        "--no-preview",
        help="Skip PNG preview rendering (use when no rendering backend is available).",
    ),
) -> None:
    """Ingest a PPTX deck into the slide library — one SlideRecord per slide.

    Running this command twice against the same file is safe: existing records
    are updated in place (idempotent upsert).
    """
    from slidestein.config import get_settings
    from slidestein.ingestion.service import IngestionService
    from slidestein.library.store import SlideLibrary
    from slidestein.pptx.python_pptx_adapter import PythonPptxAdapter

    if not source.exists():
        console.print(f"[red]File not found:[/red] {source}")
        raise typer.Exit(1)
    if source.suffix.lower() != ".pptx":
        console.print(f"[red]Expected a .pptx file, got:[/red] {source.suffix}")
        raise typer.Exit(1)

    settings = get_settings()
    render = not no_preview

    console.print(f"[bold cyan]SlideStein[/bold cyan]  indexing {source.name}")
    if not render:
        console.print("  [dim]Preview rendering disabled[/dim]")

    try:
        with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
            service = IngestionService(
                library=library,
                adapter=PythonPptxAdapter(),
                previews_dir=settings.previews_dir,
            )
            records = service.ingest_deck(source, render_previews=render)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except RuntimeError as exc:
        console.print(f"[red]Rendering error:[/red] {exc}")
        console.print("Tip: re-run with [bold]--no-preview[/bold] to skip rendering.")
        raise typer.Exit(1) from exc

    for r in records:
        preview_indicator = "[P]" if r.preview_path else "   "
        console.print(
            f"  [green]ok[/green] slide {r.slide_number:>3}  "
            f"[cyan]{r.slide_id}[/cyan]  {preview_indicator}  "
            f"{r.shape_count} shape(s)"
        )

    console.print(
        f"\nIndexed [bold]{len(records)}[/bold] slide(s) from {source.name}."
    )


@app.command()
def status() -> None:
    """Show slide library statistics."""
    from slidestein.config import get_settings
    from slidestein.library.store import SlideLibrary

    settings = get_settings()

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        decks = library.list_decks()
        total_slides = library.count_records()
        with_previews = library.count_records_with_preview()
        classified = library.count_classified_records()
        with_embeddings = library.count_records_with_embeddings()

    # Summary panel
    summary = Table(title="SlideStein Library", show_header=False, box=None, padding=(0, 2))
    summary.add_column(style="dim")
    summary.add_column(justify="right", style="bold")

    summary.add_row("Indexed decks", str(len(decks)))
    summary.add_row("Indexed slides", str(total_slides))
    summary.add_row("Slides with previews", str(with_previews))
    summary.add_row("Slides classified", str(classified))
    summary.add_row("Slides with embeddings", str(with_embeddings))

    console.print(summary)

    if not decks:
        console.print(
            "\n[dim]No decks indexed yet.  "
            "Run: [bold]slidestein index path/to/deck.pptx[/bold][/dim]"
        )
        return

    # Per-deck breakdown
    console.print()
    deck_table = Table(title="Indexed Decks")
    deck_table.add_column("Deck ID", style="dim")
    deck_table.add_column("Fingerprint", style="cyan")
    deck_table.add_column("Slides", justify="right")
    deck_table.add_column("Source path")

    for d in decks:
        deck_table.add_row(
            (d["deck_id"] or "")[:8] + "…" if d.get("deck_id") else "—",
            d["fingerprint"][:12],
            str(d["slide_count"]),
            d["path"],
        )

    console.print(deck_table)


@app.command("extract-slide")
def extract_slide(
    source: Path = typer.Argument(..., help="Path to the source .pptx file."),
    slide_number: int = typer.Argument(..., help="1-indexed slide number to extract."),
    output: Path = typer.Option(
        Path("outputs/slide.pptx"),
        "--output",
        "-o",
        help="Destination path for the extracted PPTX.",
    ),
) -> None:
    """Extract a single slide from an existing deck via PPT Master's native roundtrip.

    The extracted slide retains its original OOXML — shapes, charts, tables, and
    SmartArt remain natively editable.  A PNG preview of the output is rendered
    alongside the PPTX.
    """
    from slidestein.config import get_settings
    from slidestein.pptx.pptmaster_real_adapter import PPTMasterRealAdapter, PPTMasterError

    if not source.exists():
        console.print(f"[red]File not found:[/red] {source}")
        raise typer.Exit(1)
    if source.suffix.lower() != ".pptx":
        console.print(f"[red]Expected a .pptx file, got:[/red] {source.suffix}")
        raise typer.Exit(1)
    if slide_number < 1:
        console.print(f"[red]slide-number must be >= 1, got:[/red] {slide_number}")
        raise typer.Exit(1)

    settings = get_settings()
    console.print(
        f"[bold cyan]SlideStein[/bold cyan]  extracting slide {slide_number} "
        f"from {source.name}"
    )

    try:
        adapter = PPTMasterRealAdapter.from_settings(settings)
        console.print(f"  ppt-master: {adapter._cli}")
        result_pptx = adapter.extract_slide(
            source_pptx=source.resolve(),
            slide_number=slide_number,
            output_path=output,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]ppt-master not found:[/red] {exc}")
        raise typer.Exit(1) from exc
    except PPTMasterError as exc:
        console.print(f"[red]ppt-master error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"  [green]ok[/green]  PPTX -> {result_pptx}")

    # Render PNG preview of slide 1 in the output (single-slide deck)
    png_path = result_pptx.with_suffix(".png")
    try:
        adapter.render_preview(result_pptx, slide_number=1, output_path=png_path)
        console.print(f"  [green]ok[/green]  PNG  -> {png_path}")
    except RuntimeError as exc:
        console.print(f"  [yellow]preview skipped:[/yellow] {exc}")

    console.print(f"\nDone. Slide {slide_number} extracted to {output}")


@app.command("test-fill")
def test_fill(
    source: Path = typer.Argument(..., help="Path to the source .pptx file."),
    slide_number: int = typer.Argument(..., help="1-indexed slide number to modify."),
    replace: tuple[str, str] = typer.Option(
        ...,
        "--replace",
        help="Text replacement pair: --replace OLD_TEXT NEW_TEXT",
    ),
    output: Path = typer.Option(
        Path("outputs/slide_modified.pptx"),
        "--output",
        "-o",
        help="Destination path for the modified PPTX.",
    ),
) -> None:
    """Technical roundtrip test: replace text in a slide and export via PPT Master.

    This command validates the native roundtrip without AI content drafting.
    Only the specified text is replaced; all other objects are preserved.
    A PNG preview of the output is rendered alongside the PPTX.
    """
    from slidestein.config import get_settings
    from slidestein.pptx.pptmaster_real_adapter import PPTMasterRealAdapter, PPTMasterError

    old_text, new_text = replace

    if not source.exists():
        console.print(f"[red]File not found:[/red] {source}")
        raise typer.Exit(1)
    if source.suffix.lower() != ".pptx":
        console.print(f"[red]Expected a .pptx file, got:[/red] {source.suffix}")
        raise typer.Exit(1)
    if slide_number < 1:
        console.print(f"[red]slide-number must be >= 1, got:[/red] {slide_number}")
        raise typer.Exit(1)

    settings = get_settings()
    console.print(
        f"[bold cyan]SlideStein[/bold cyan]  test-fill slide {slide_number} "
        f"of {source.name}"
    )
    console.print(f"  replacing: {old_text!r} -> {new_text!r}")

    try:
        adapter = PPTMasterRealAdapter.from_settings(settings)
        result_pptx = adapter.replace_text_in_slide(
            source_pptx=source.resolve(),
            slide_number=slide_number,
            replacements={old_text: new_text},
            output_path=output,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]ppt-master not found:[/red] {exc}")
        raise typer.Exit(1) from exc
    except PPTMasterError as exc:
        console.print(f"[red]ppt-master error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"  [green]ok[/green]  PPTX -> {result_pptx}")

    # Render PNG preview
    png_path = result_pptx.with_suffix(".png")
    try:
        adapter.render_preview(result_pptx, slide_number=1, output_path=png_path)
        console.print(f"  [green]ok[/green]  PNG  -> {png_path}")
    except RuntimeError as exc:
        console.print(f"  [yellow]preview skipped:[/yellow] {exc}")

    console.print(f"\nDone. Modified slide written to {output}")


@app.command("inspect-text")
def inspect_text(
    source: Path = typer.Argument(..., help="Path to a .pptx file to inspect."),
    slide: int = typer.Option(
        1, "--slide", "-s", help="Slide number to inspect (1-indexed, default 1)."
    ),
) -> None:
    """Enumerate text-bearing shapes on a slide.

    Shows the shape ID, name, and a text preview for every shape that contains
    text on the given slide.  Use this to identify which shapes are candidates
    for native-fill text replacement.

    Shape IDs here match the IDs used by native-fill's PowerPoint COM editor.
    """
    from pptx import Presentation
    from rich.table import Table

    if not source.exists():
        console.print(f"[red]File not found:[/red] {source}")
        raise typer.Exit(1)
    if source.suffix.lower() != ".pptx":
        console.print(f"[red]Expected a .pptx file, got:[/red] {source.suffix}")
        raise typer.Exit(1)

    prs = Presentation(str(source))
    if slide < 1 or slide > len(prs.slides):
        console.print(
            f"[red]Slide {slide} out of range:[/red] this file has {len(prs.slides)} slide(s)"
        )
        raise typer.Exit(1)

    sl = prs.slides[slide - 1]

    table = Table(
        title=f"Text shapes - {source.name}  slide {slide}",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Shape ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold", no_wrap=True)
    table.add_column("Text preview")

    count = 0
    for shape in sl.shapes:
        if not shape.has_text_frame:
            continue
        text = shape.text_frame.text
        if not text.strip():
            continue
        preview = text[:80].replace("\n", " | ").replace("\r", " | ").replace("\x0b", " | ")
        if len(text) > 80:
            preview += "..."
        table.add_row(str(shape.shape_id), shape.name, preview)
        count += 1

    if count == 0:
        console.print(f"[dim]No text-bearing shapes found on slide {slide}.[/dim]")
        return

    console.print(table)
    console.print(f"\n[dim]{count} text shape(s) on slide {slide}[/dim]")


@app.command("native-fill")
def native_fill(
    source: Path = typer.Argument(..., help="Path to the source .pptx deck."),
    slide_number: int = typer.Argument(..., help="1-indexed slide number to edit."),
    replace: tuple[str, str] = typer.Option(
        ...,
        "--replace",
        help="Text replacement pair: --replace OLD_TEXT NEW_TEXT",
    ),
    output: Path = typer.Option(
        Path("outputs/slide_native_modified.pptx"),
        "--output",
        "-o",
        help="Destination path for the native-edited PPTX.",
    ),
) -> None:
    """Extract a slide natively and replace text via PowerPoint COM.

    Internal flow:
      1. Extract the slide via PPT Master native roundtrip (byte-for-byte passthrough).
      2. Open the extracted PPTX in Microsoft PowerPoint COM.
      3. Replace text in-place, preserving per-run character formatting.
      4. Save to the requested output path.
      5. Render a PNG preview using PowerPoint COM.
      6. Report which OPC package parts changed.

    This does NOT rebuild the slide through SVG.  Complex effects, charts,
    tables, SmartArt, and grouping are preserved natively.
    """
    import tempfile

    from slidestein.config import get_settings
    from slidestein.pptx.com_editor import (
        PowerPointComEditor,
        PowerPointComEditorError,
        ReplacementStatus,
    )
    from slidestein.pptx.opc_diff import compare_pptx_packages
    from slidestein.pptx.pptmaster_real_adapter import PPTMasterError, PPTMasterRealAdapter
    from slidestein.pptx.python_pptx_adapter import PythonPptxAdapter

    old_text, new_text = replace

    if not source.exists():
        console.print(f"[red]File not found:[/red] {source}")
        raise typer.Exit(1)
    if source.suffix.lower() != ".pptx":
        console.print(f"[red]Expected a .pptx file, got:[/red] {source.suffix}")
        raise typer.Exit(1)
    if slide_number < 1:
        console.print(f"[red]slide-number must be >= 1, got:[/red] {slide_number}")
        raise typer.Exit(1)

    settings = get_settings()
    console.print(
        f"[bold cyan]SlideStein[/bold cyan]  native-fill slide {slide_number} "
        f"of {source.name}"
    )
    console.print(f"  replacing: {old_text!r} -> {new_text!r}")

    # Step 1 — extract via PPT Master native roundtrip
    try:
        pptmaster_adapter = PPTMasterRealAdapter.from_settings(settings)
    except FileNotFoundError as exc:
        console.print(f"[red]ppt-master not found:[/red] {exc}")
        raise typer.Exit(1) from exc

    with tempfile.TemporaryDirectory() as tmpdir:
        extracted_pptx = Path(tmpdir) / "extracted.pptx"

        try:
            console.print("  [dim]1/4  Extracting slide via PPT Master...[/dim]")
            pptmaster_adapter.extract_slide(
                source_pptx=source.resolve(),
                slide_number=slide_number,
                output_path=extracted_pptx,
            )
        except PPTMasterError as exc:
            console.print(f"[red]ppt-master error:[/red] {exc}")
            raise typer.Exit(1) from exc

        console.print(
            f"  [green]ok[/green]  extracted {extracted_pptx.stat().st_size:,} bytes "
            "(native passthrough: original OOXML preserved)"
        )

        # Step 2-3 — native COM text replacement
        editor = PowerPointComEditor()
        try:
            console.print("  [dim]2/4  Replacing text via PowerPoint COM...[/dim]")
            results = editor.replace_text(
                source_pptx=extracted_pptx,
                replacements={old_text: new_text},
                output_path=output,
            )
        except PowerPointComEditorError as exc:
            console.print(f"[red]PowerPoint COM error:[/red] {exc}")
            raise typer.Exit(1) from exc

        has_error = False
        for r in results:
            if r.status == ReplacementStatus.REPLACED_AND_VERIFIED:
                console.print(
                    f"  [green]ok[/green]  {r.requested!r} -> {r.replacement!r}: "
                    f"REPLACED_AND_VERIFIED "
                    f"({r.occurrences_before} occurrence(s) -> {r.occurrences_after})"
                )
            elif r.status == ReplacementStatus.NO_MATCH:
                console.print(
                    f"  [yellow]warning:[/yellow] {r.requested!r} not found "
                    f"in slide {slide_number}"
                )
            elif r.status == ReplacementStatus.ERROR:
                console.print(
                    f"  [red]error:[/red] replacement failed verification "
                    f"for {r.requested!r}: {r.error}"
                )
                has_error = True

        console.print(f"  [green]ok[/green]  PPTX -> {output}")

        # Step 4 - OPC package diff
        console.print("  [dim]3/4  Comparing OPC packages...[/dim]")
        try:
            diff = compare_pptx_packages(extracted_pptx, output)
            _print_opc_diff(diff)
        except Exception as exc:
            console.print(f"  [yellow]OPC diff skipped:[/yellow] {exc}")

    # Step 5 — PNG preview (outside temp dir; only needs output)
    png_path = output.with_suffix(".png")
    try:
        console.print("  [dim]4/4  Rendering preview...[/dim]")
        PythonPptxAdapter().render_preview(output, slide_number=1, output_path=png_path)
        console.print(f"  [green]ok[/green]  PNG  -> {png_path}")
    except RuntimeError as exc:
        console.print(f"  [yellow]preview skipped:[/yellow] {exc}")

    if has_error:
        console.print(
            "\n[red]Verification failed: output file may not reflect "
            "requested changes.[/red]"
        )
        raise typer.Exit(1)

    console.print(f"\nDone. Native-edited slide written to [bold]{output}[/bold]")


def _print_opc_diff(diff: dict[str, list[str]]) -> None:
    """Print a concise OPC package diff summary."""
    changed = diff.get("changed", [])
    added = diff.get("added", [])
    removed = diff.get("removed", [])
    unchanged_count = len(diff.get("unchanged", []))

    if not changed and not added and not removed:
        console.print(
            f"  [dim]OPC diff: no structural changes ({unchanged_count} parts identical)[/dim]"
        )
        return

    console.print("  OPC package diff (extracted -> native-edited):")
    if changed:
        console.print(f"    [yellow]Changed  ({len(changed)}):[/yellow]")
        for p in changed:
            console.print(f"      {p}")
    if added:
        console.print(f"    [cyan]Added    ({len(added)}):[/cyan]")
        for p in added:
            console.print(f"      {p}")
    if removed:
        console.print(f"    [red]Removed  ({len(removed)}):[/red]")
        for p in removed:
            console.print(f"      {p}")
    console.print(f"    [dim]Unchanged: {unchanged_count} parts[/dim]")


@app.command("classify-slide")
def classify_slide(
    source: Path = typer.Argument(..., help="Path to the source .pptx file."),
    slide_number: int = typer.Argument(..., help="1-indexed slide number to classify."),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the JSON profile to this file (default: print to stdout).",
    ),
) -> None:
    """Classify a single slide and output its semantic profile as JSON.

    Uses Claude Vision to identify the communication job, visual archetype,
    and structural pattern of the requested slide.  The source presentation
    is never modified.

    Without --output the JSON profile is printed to stdout (clean for piping).
    With --output progress is shown and the profile is written to the file.
    If the slide is indexed in the library, the classification is persisted.
    """
    from slidestein.classification.classifier import (
        SlideClassificationError,
    )
    from slidestein.classification.providers.factory import create_slide_classifier
    from slidestein.classification.service import SlideClassificationService
    from slidestein.classification.versions import CLASSIFICATION_VERSION, PROMPT_VERSION
    from slidestein.config import get_settings
    from slidestein.identity.slide_identity import (
        compute_content_fingerprint,
        compute_deck_fingerprint,
        compute_input_fingerprint,
        compute_structure_fingerprint,
    )
    from slidestein.library.store import SlideLibrary
    from slidestein.pptx.python_pptx_adapter import PythonPptxAdapter

    if not source.exists():
        console.print(f"[red]File not found:[/red] {source}")
        raise typer.Exit(1)
    if source.suffix.lower() != ".pptx":
        console.print(f"[red]Expected a .pptx file, got:[/red] {source.suffix}")
        raise typer.Exit(1)
    if slide_number < 1:
        console.print(f"[red]slide-number must be >= 1, got:[/red] {slide_number}")
        raise typer.Exit(1)

    if output is not None:
        console.print(
            f"[bold cyan]SlideStein[/bold cyan]  classify-slide {slide_number} "
            f"from {source.name}"
        )

    settings = get_settings()

    # Look up the indexed record to get the stable slide_id and existing preview.
    resolved_source = source.resolve()
    deck_fp = compute_deck_fingerprint(resolved_source)

    indexed_record = None
    existing_preview: Path | None = None
    stable_slide_id: str | None = None

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        indexed_record = library.get_record_by_deck_and_slide(deck_fp, slide_number)

    if indexed_record is not None:
        stable_slide_id = indexed_record.slide_id
        if indexed_record.preview_path is not None:
            pp = Path(str(indexed_record.preview_path))
            if pp.exists():
                existing_preview = pp

    if output is not None:
        console.print("  [dim]classifying...[/dim]")

    from slidestein.classification.providers.factory import create_slide_classifier

    service = SlideClassificationService(
        classifier=create_slide_classifier(settings),
        renderer=PythonPptxAdapter(),
    )

    try:
        profile = service.classify_slide(
            pptx_path=resolved_source,
            slide_number=slide_number,
            slide_id=stable_slide_id,
            existing_preview_path=existing_preview,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except SlideClassificationError as exc:
        console.print(f"[red]Classification error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except RuntimeError as exc:
        console.print(f"[red]Rendering error:[/red] {exc}")
        raise typer.Exit(1) from exc

    # Persist classification if slide is indexed.
    if indexed_record is not None:
        content_fp = indexed_record.content_fingerprint or ""
        structure_fp = indexed_record.structure_fingerprint or ""
        input_fp = compute_input_fingerprint(
            profile.slide_id, content_fp, structure_fp,
            CLASSIFICATION_VERSION, PROMPT_VERSION,
        )
        model_name = service._classifier._model  # type: ignore[attr-defined]
        with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
            library.upsert_classification(
                slide_id=profile.slide_id,
                version=CLASSIFICATION_VERSION,
                model=model_name,
                prompt_version=PROMPT_VERSION,
                input_fingerprint=input_fp,
                profile=profile,
            )
        if output is not None:
            console.print("  [green]ok[/green]  classification persisted")
    elif output is not None:
        console.print("  [yellow]note:[/yellow] slide not indexed — profile not persisted")

    json_str = profile.model_dump_json(indent=2)

    if output is None:
        typer.echo(json_str)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json_str, encoding="utf-8")
        job_val = profile.primary_communication_job.value if profile.primary_communication_job else "null"
        console.print(
            f"\n  [green]ok[/green]  communication job: "
            f"[cyan]{job_val}[/cyan]"
        )
        console.print(
            f"  [green]ok[/green]  visual archetype: "
            f"[cyan]{profile.visual_archetype.value}[/cyan]"
        )
        console.print(f"  [green]ok[/green]  profile -> {output}")


@app.command("classify-all")
def classify_all(
    force: bool = typer.Option(
        False,
        "--force",
        help="Reclassify even slides that already have a current classification.",
    ),
    deck_id: Optional[str] = typer.Option(
        None,
        "--deck-id",
        help="Limit to slides from this deck ID.",
    ),
) -> None:
    """Classify all active indexed slides and persist results.

    Skips slides whose classification is already current (input fingerprint
    unchanged).  Use --force to reclassify everything regardless.

    Does NOT call the real Anthropic API automatically — it uses the injected
    classifier from SlideClassificationService.  For testing, inject a mock.
    """
    from slidestein.classification.classifier import (
        SlideClassificationError,
    )
    from slidestein.classification.providers.factory import create_slide_classifier
    from slidestein.classification.service import SlideClassificationService
    from slidestein.classification.versions import CLASSIFICATION_VERSION, PROMPT_VERSION
    from slidestein.config import get_settings
    from slidestein.identity.slide_identity import compute_input_fingerprint
    from slidestein.library.store import SlideLibrary
    from slidestein.pptx.python_pptx_adapter import PythonPptxAdapter

    settings = get_settings()

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        active = library.list_active_slides()

        if deck_id is not None:
            active = [r for r in active if r.deck_id == deck_id]

        if not active:
            console.print("[bold cyan]SlideStein[/bold cyan]  classify-all")
            console.print("  No active slides found.")
            return

        console.print(
            f"[bold cyan]SlideStein[/bold cyan]  classify-all\n"
            f"  Checking {len(active)} active slide(s)...\n"
        )

        service = SlideClassificationService(
            classifier=create_slide_classifier(settings),
            renderer=PythonPptxAdapter(),
        )

        n_skipped = 0
        n_classified = 0
        n_reclassified = 0
        n_failed = 0

        for record in active:
            content_fp = record.content_fingerprint or ""
            structure_fp = record.structure_fingerprint or ""
            current_input_fp = compute_input_fingerprint(
                record.slide_id, content_fp, structure_fp,
                CLASSIFICATION_VERSION, PROMPT_VERSION,
            )

            already_current = library.classification_is_current(
                record.slide_id, CLASSIFICATION_VERSION, current_input_fp
            )

            if already_current and not force:
                n_skipped += 1
                continue

            was_classified = already_current  # True only when --force re-classifying

            existing_preview: Path | None = None
            if record.preview_path is not None:
                pp = Path(str(record.preview_path))
                if pp.exists():
                    existing_preview = pp

            try:
                profile = service.classify_slide(
                    pptx_path=Path(str(record.source_deck_path)),
                    slide_number=record.slide_number,
                    slide_id=record.slide_id,
                    existing_preview_path=existing_preview,
                )
            except (SlideClassificationError, FileNotFoundError, ValueError, RuntimeError) as exc:
                console.print(
                    f"  [red]error[/red]  slide {record.slide_number} "
                    f"({record.slide_id[:8]}…): {exc}"
                )
                n_failed += 1
                continue

            model_name = service._classifier._model  # type: ignore[attr-defined]
            library.upsert_classification(
                slide_id=profile.slide_id,
                version=CLASSIFICATION_VERSION,
                model=model_name,
                prompt_version=PROMPT_VERSION,
                input_fingerprint=current_input_fp,
                profile=profile,
            )

            if was_classified:
                n_reclassified += 1
            else:
                n_classified += 1

        console.print(f"  Current / skipped  {n_skipped:>6}")
        console.print(f"  Classified         {n_classified:>6}")
        console.print(f"  Reclassified       {n_reclassified:>6}")
        console.print(f"  Failed             {n_failed:>6}")
        console.print("\n  Done.")

        if n_failed > 0:
            raise typer.Exit(1)


@app.command("classifications")
def classifications(
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write classifications as a JSON array to this file.",
    ),
    version: Optional[str] = typer.Option(
        None,
        "--version",
        help="Filter by classification version (default: all).",
    ),
) -> None:
    """Review persisted slide classifications.

    Without --output, prints a Rich table to the console.
    With --output, writes a JSON array of all classification records.
    """
    from slidestein.config import get_settings
    from slidestein.library.store import SlideLibrary

    settings = get_settings()

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        records = library.list_classifications(version=version, active_slides_only=True)

    if not records:
        console.print("[dim]No classifications found.[/dim]")
        return

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        data = [
            {
                "slide_id": r.slide_id,
                "classification_version": r.classification_version,
                "model": r.model,
                "prompt_version": r.prompt_version,
                "input_fingerprint": r.input_fingerprint,
                "profile": r.profile.model_dump(),
                "classified_at": r.classified_at,
            }
            for r in records
        ]
        output.write_text(_json.dumps(data, indent=2), encoding="utf-8")
        console.print(
            f"[green]ok[/green]  {len(records)} classification(s) -> {output}"
        )
        return

    table = Table(title=f"Classifications ({len(records)})")
    table.add_column("Slide ID", style="cyan", no_wrap=True)
    table.add_column("Job", style="bold")
    table.add_column("Archetype")
    table.add_column("Density")
    table.add_column("Version", style="dim")
    table.add_column("Classified at", style="dim")

    for r in records:
        table.add_row(
            r.slide_id[:12] + "…" if len(r.slide_id) > 12 else r.slide_id,
            r.profile.primary_communication_job.value,
            r.profile.visual_archetype.value,
            r.profile.density.value,
            r.classification_version,
            r.classified_at[:16] if r.classified_at else "",
        )

    console.print(table)


@app.command("embed-all")
def embed_all(
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-embed even slides that already have a current embedding.",
    ),
) -> None:
    """Build or refresh the semantic embedding index for all active slides.

    Skips slides whose embedding input fingerprint is already current.
    Slides with no current V2 classification are skipped (counted as unclassified).
    Uses batch embedding where possible.
    """
    from slidestein.classification.versions import CLASSIFICATION_VERSION
    from slidestein.config import get_settings
    from slidestein.library.store import SlideLibrary
    from slidestein.retrieval.document import build_retrieval_document
    from slidestein.retrieval.fingerprint import EmbeddingConfig, compute_embedding_fingerprint
    from slidestein.retrieval.providers.factory import create_embedding_provider
    from slidestein.retrieval.store import EmbeddingRecord, SlideVectorStore
    from slidestein.retrieval.versions import EMBEDDING_VERSION

    settings = get_settings()

    console.print("[bold cyan]SlideStein[/bold cyan]  embed-all")

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        active = library.list_active_slides()

    if not active:
        console.print("  No active slides found.")
        return

    console.print(f"  Checking {len(active)} active slide(s)...\n")

    provider = create_embedding_provider(settings)
    vector_store = SlideVectorStore(settings.lancedb_uri)

    embedding_cfg = EmbeddingConfig(
        version=EMBEDDING_VERSION,
        provider=settings.embedding_provider,
        model=settings.sap_ai_core_embedding_model,
        normalize=True,
    )

    # Gather slides needing embedding.
    to_embed: list[tuple] = []   # (record, classification, retrieval_text, fingerprint)
    n_skipped = 0
    n_unclassified = 0

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        for record in active:
            cls_rec = library.get_classification(record.slide_id, CLASSIFICATION_VERSION)
            if cls_rec is None:
                n_unclassified += 1
                continue

            retrieval_text = build_retrieval_document(cls_rec.profile)
            fp = compute_embedding_fingerprint(retrieval_text, embedding_cfg)

            if not force and vector_store.is_current(record.slide_id, fp):
                n_skipped += 1
                continue

            to_embed.append((record, cls_rec, retrieval_text, fp))

    n_embedded = 0
    n_failed = 0

    if to_embed:
        # Batch embed all stale slides.
        texts = [item[2] for item in to_embed]
        try:
            batch = provider.embed_documents(texts)
        except Exception as exc:
            console.print(f"  [red]Embedding error:[/red] {exc}")
            raise typer.Exit(1) from exc

        # Build records and upsert.
        emb_records: list[EmbeddingRecord] = []
        vectors: list[list[float]] = []

        for (record, cls_rec, retrieval_text, fp), vec in zip(to_embed, batch.vectors):
            profile = cls_rec.profile
            job_val = profile.primary_communication_job.value if profile.primary_communication_job else ""
            secondary_jobs_val = ",".join(j.value for j in profile.secondary_communication_jobs)
            roles_val = ",".join(r.value for r in profile.storyline_roles)
            emb_records.append(
                EmbeddingRecord(
                    slide_id=record.slide_id,
                    deck_id=record.deck_id or "",
                    slide_number=record.slide_number,
                    embedding_version=EMBEDDING_VERSION,
                    embedding_provider=settings.embedding_provider,
                    embedding_model=batch.model,
                    embedding_input_fingerprint=fp,
                    classification_version=CLASSIFICATION_VERSION,
                    retrieval_text=retrieval_text,
                    slide_function=profile.slide_function.value,
                    primary_communication_job=job_val,
                    secondary_communication_jobs=secondary_jobs_val,
                    storyline_roles=roles_val,
                    visual_archetype=profile.visual_archetype.value,
                    density=profile.density.value,
                    description=profile.description,
                    is_active=True,
                )
            )
            vectors.append(vec)

        try:
            vector_store.upsert_batch(emb_records, vectors)
            n_embedded = len(emb_records)
        except Exception as exc:
            console.print(f"  [red]Vector store error:[/red] {exc}")
            raise typer.Exit(1) from exc

    # Deactivate vectors for slides no longer active.
    active_ids = {r.slide_id for r in active}
    tbl = vector_store._get_table()
    if tbl is not None:
        try:
            all_active_rows = (
                tbl.search()
                .where("is_active = true", prefilter=True)
                .select(["slide_id"])
                .limit(None)
                .to_list()
            )
            stale_ids = [
                row["slide_id"]
                for row in all_active_rows
                if row["slide_id"] not in active_ids
            ]
            if stale_ids:
                vector_store.deactivate_slides(stale_ids)
        except Exception:
            pass  # Non-critical cleanup

    console.print(f"  Active slides      {len(active):>6}")
    console.print(f"  Current / skipped  {n_skipped:>6}")
    console.print(f"  Embedded           {n_embedded:>6}")
    console.print(f"  Unclassified       {n_unclassified:>6}")
    console.print(f"  Failed             {n_failed:>6}")
    console.print("\n  Done.")

    if n_failed > 0:
        raise typer.Exit(1)


@app.command("semantic-search")
def semantic_search(
    query: str = typer.Argument(..., help="Natural-language search query."),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results to return."),
) -> None:
    """Search the slide index by semantic similarity.

    Returns the top-k slides ranked by cosine similarity to the query.
    Pure vector retrieval — no hybrid scoring or reranking.
    """
    from slidestein.config import get_settings
    from slidestein.retrieval.providers.factory import create_embedding_provider
    from slidestein.retrieval.search import SemanticSlideSearch
    from slidestein.retrieval.store import SlideVectorStore

    if not query.strip():
        console.print("[red]Error:[/red] query must not be blank.")
        raise typer.Exit(1)
    if top_k <= 0:
        console.print("[red]Error:[/red] --top-k must be > 0.")
        raise typer.Exit(1)

    settings = get_settings()

    try:
        provider = create_embedding_provider(settings)
        store = SlideVectorStore(settings.lancedb_uri)
        searcher = SemanticSlideSearch(provider=provider, store=store)
        results = searcher.search(query, top_k=top_k)
    except Exception as exc:
        console.print(f"[red]Search error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"\n[bold cyan]Semantic search[/bold cyan]")
    console.print(f"Query: [italic]{query}[/italic]\n")

    if not results:
        console.print("[dim]No results found. Run embed-all first.[/dim]")
        return

    for r in results:
        job_display = r.primary_communication_job or "null"
        console.print(
            f"[bold]#{r.rank}[/bold]  Slide {r.slide_number} "
            f"([dim]{r.slide_id[:8]}…[/dim])"
        )
        console.print(f"     distance:  {r.distance:.4f}")
        console.print(f"     function:  {r.slide_function}")
        console.print(f"     job:       {job_display}")
        console.print(f"     archetype: {r.visual_archetype}")
        console.print()


@app.command("metadata-sync")
def metadata_sync() -> None:
    """Rebuild the LanceDB table with enriched metadata columns.

    Reads current V2 classifications from the library, builds updated EmbeddingRecord
    objects (with secondary_communication_jobs and storyline_roles), then rebuilds the
    LanceDB table in-place — existing vectors are preserved, no SAP calls are made.

    Safe to run multiple times.  The old table is replaced atomically.
    """
    from slidestein.classification.versions import CLASSIFICATION_VERSION
    from slidestein.config import get_settings
    from slidestein.library.store import SlideLibrary
    from slidestein.retrieval.fingerprint import EmbeddingConfig, compute_embedding_fingerprint
    from slidestein.retrieval.store import EmbeddingRecord, SlideVectorStore
    from slidestein.retrieval.versions import EMBEDDING_VERSION

    settings = get_settings()
    console.print("[bold cyan]SlideStein[/bold cyan]  metadata-sync")

    vector_store = SlideVectorStore(settings.lancedb_uri)

    if not vector_store.table_exists():
        console.print("  [red]Error:[/red] No vector table found. Run embed-all first.")
        raise typer.Exit(1)

    dim = vector_store.dimension()
    if dim is None:
        console.print("  [red]Error:[/red] Could not determine table dimension.")
        raise typer.Exit(1)

    console.print(f"  Table exists — dimension: {dim}")

    # Build enriched records from current V2 classifications.
    enriched: list[EmbeddingRecord] = []

    embedding_cfg = EmbeddingConfig(
        version=EMBEDDING_VERSION,
        provider=settings.embedding_provider,
        model=settings.sap_ai_core_embedding_model,
        normalize=True,
    )

    with SlideLibrary(settings.db_path, settings.lancedb_uri) as library:
        active = library.list_active_slides()
        from slidestein.retrieval.document import build_retrieval_document

        for record in active:
            cls_rec = library.get_classification(record.slide_id, CLASSIFICATION_VERSION)
            if cls_rec is None:
                continue
            profile = cls_rec.profile
            retrieval_text = build_retrieval_document(profile)
            fp = compute_embedding_fingerprint(retrieval_text, embedding_cfg)
            job_val = profile.primary_communication_job.value if profile.primary_communication_job else ""
            secondary_jobs_val = ",".join(j.value for j in profile.secondary_communication_jobs)
            roles_val = ",".join(r.value for r in profile.storyline_roles)
            enriched.append(
                EmbeddingRecord(
                    slide_id=record.slide_id,
                    deck_id=record.deck_id or "",
                    slide_number=record.slide_number,
                    embedding_version=EMBEDDING_VERSION,
                    embedding_provider=settings.embedding_provider,
                    embedding_model=settings.sap_ai_core_embedding_model,
                    embedding_input_fingerprint=fp,
                    classification_version=CLASSIFICATION_VERSION,
                    retrieval_text=retrieval_text,
                    slide_function=profile.slide_function.value,
                    primary_communication_job=job_val,
                    secondary_communication_jobs=secondary_jobs_val,
                    storyline_roles=roles_val,
                    visual_archetype=profile.visual_archetype.value,
                    density=profile.density.value,
                    description=profile.description,
                    is_active=True,
                )
            )

    if not enriched:
        console.print(
            "  [yellow]Warning:[/yellow] No classified slides found. "
            "Run classify-all before metadata-sync."
        )
        raise typer.Exit(1)

    console.print(f"  Enriched records built: {len(enriched)}")
    console.print("  Rebuilding table (preserving vectors)...")

    try:
        n_written = vector_store.rebuild_with_enriched_metadata(enriched, expected_dim=dim)
    except Exception as exc:
        console.print(f"  [red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"  [green]ok[/green]  Table rebuilt — {n_written} row(s) written.")
    console.print("\n  Done.")


@app.command("hybrid-search")
def hybrid_search(
    query: str = typer.Argument(..., help="Natural-language description of the desired slide."),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results to return."),
    function: Optional[str] = typer.Option(
        None, "--function", "-f", help="Slide function filter (cover, content, section_divider, closing)."
    ),
    job: Optional[str] = typer.Option(
        None, "--job", "-j", help="Primary communication job (explain, summarise, show_timeline, …)."
    ),
    archetype: Optional[list[str]] = typer.Option(
        None, "--archetype", "-a", help="Preferred visual archetypes (repeatable)."
    ),
    role: Optional[list[str]] = typer.Option(
        None, "--role", "-r", help="Required storyline roles (repeatable)."
    ),
    density: Optional[str] = typer.Option(
        None, "--density", "-d", help="Density filter (low, medium, high)."
    ),
    required: Optional[list[str]] = typer.Option(
        None, "--required", help="Required content element (repeatable, appended to query)."
    ),
    strict_function: bool = typer.Option(
        False, "--strict-function", help="Exclude slides that do not match --function exactly."
    ),
) -> None:
    """Search slides with hybrid semantic + metadata scoring.

    Combines vector similarity with structured filters (slide_function, communication
    job, archetypes, storyline roles, density).  Unspecified dimensions are excluded
    from scoring — specifying only --query gives pure semantic ranking.
    """
    from slidestein.config import get_settings
    from slidestein.domain.models import (
        CommunicationJob,
        DensityLevel,
        SlideFunction,
        StorylineRole,
        VisualArchetype,
    )
    from slidestein.retrieval.hybrid import HybridSlideSearch
    from slidestein.retrieval.providers.factory import create_embedding_provider
    from slidestein.retrieval.request import SlideRetrievalRequest
    from slidestein.retrieval.store import SlideVectorStore

    if not query.strip():
        console.print("[red]Error:[/red] query must not be blank.")
        raise typer.Exit(1)

    # Parse optional enum values.
    fn_enum: Optional[SlideFunction] = None
    if function is not None:
        try:
            fn_enum = SlideFunction(function)
        except ValueError:
            console.print(f"[red]Error:[/red] Unknown slide function: {function!r}")
            raise typer.Exit(1)

    job_enum: Optional[CommunicationJob] = None
    if job is not None:
        try:
            job_enum = CommunicationJob(job)
        except ValueError:
            console.print(f"[red]Error:[/red] Unknown communication job: {job!r}")
            raise typer.Exit(1)

    archetype_enums: Optional[list[VisualArchetype]] = None
    if archetype:
        try:
            archetype_enums = [VisualArchetype(a) for a in archetype]
        except ValueError as exc:
            console.print(f"[red]Error:[/red] Unknown archetype: {exc}")
            raise typer.Exit(1)

    role_enums: Optional[list[StorylineRole]] = None
    if role:
        try:
            role_enums = [StorylineRole(r) for r in role]
        except ValueError as exc:
            console.print(f"[red]Error:[/red] Unknown storyline role: {exc}")
            raise typer.Exit(1)

    density_enum: Optional[DensityLevel] = None
    if density is not None:
        try:
            density_enum = DensityLevel(density)
        except ValueError:
            console.print(f"[red]Error:[/red] Unknown density: {density!r}")
            raise typer.Exit(1)

    try:
        request = SlideRetrievalRequest(
            query_text=query,
            slide_function=fn_enum,
            job=job_enum,
            archetypes=archetype_enums,
            roles=role_enums,
            density=density_enum,
            required_content_elements=required or [],
            top_k=top_k,
            strict_slide_function=strict_function,
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    settings = get_settings()

    try:
        provider = create_embedding_provider(settings)
        store = SlideVectorStore(settings.lancedb_uri)
        searcher = HybridSlideSearch(provider=provider, store=store)
        results = searcher.search(request)
    except Exception as exc:
        console.print(f"[red]Search error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"\n[bold cyan]Hybrid search[/bold cyan]")
    console.print(f"Query: [italic]{query}[/italic]\n")

    if not results:
        console.print("[dim]No results found. Run metadata-sync first.[/dim]")
        return

    for r in results:
        job_display = r.primary_communication_job or "null"
        score_parts = [f"hybrid={r.hybrid_score:.4f}", f"semantic={r.semantic_score:.4f}"]
        if r.slide_function_fit is not None:
            score_parts.append(f"fn={r.slide_function_fit:.2f}")
        if r.communication_job_fit is not None:
            score_parts.append(f"job={r.communication_job_fit:.2f}")
        if r.visual_archetype_fit is not None:
            score_parts.append(f"arch={r.visual_archetype_fit:.2f}")
        if r.storyline_role_fit is not None:
            score_parts.append(f"role={r.storyline_role_fit:.2f}")
        if r.density_fit is not None:
            score_parts.append(f"dens={r.density_fit:.2f}")

        console.print(
            f"[bold]#{r.rank}[/bold]  Slide {r.slide_number} "
            f"([dim]{r.slide_id[:8]}…[/dim])"
        )
        console.print(f"     scores:    {' | '.join(score_parts)}")
        console.print(f"     distance:  {r.semantic_distance:.4f}")
        console.print(f"     function:  {r.slide_function}")
        console.print(f"     job:       {job_display}")
        console.print(f"     archetype: {r.visual_archetype}")
        console.print(f"     roles:     {r.storyline_roles or 'none'}")
        console.print()


if __name__ == "__main__":
    app()
