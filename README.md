# SlideStein

AI consulting slide generator — one slide at a time.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## Setup

```bash
uv sync
```

If uv downloads a managed Python that is blocked by your organisation's AppLocker policy, pin it to a pre-approved interpreter:

```bash
UV_PYTHON="C:\path\to\approved\python.exe" uv sync
```

A `uv.toml` in the project root already sets `python-preference = "only-system"` so uv prefers system-installed interpreters over its own managed downloads.

## Running the CLI

### Standard (where allowed)

```bash
uv run slidestein <command> [args]
```

### AppLocker-safe fallback

AppLocker policies block generated console-script `.exe` files (the shim produced in `.venv\Scripts\slidestein.exe`). Use the module invocation instead — it runs through the trusted Python interpreter:

```bash
.\.venv\Scripts\python.exe -m slidestein <command> [args]
# or, with the venv activated:
python -m slidestein <command> [args]
```

Both forms are identical in behaviour.

## Commands

### `index` — Ingest a PPTX deck

```bash
python -m slidestein index "path/to/deck.pptx"
python -m slidestein index "path/to/deck.pptx" --no-preview   # skip PNG rendering
```

Ingests one `SlideRecord` per slide into the SQLite library.  
Re-running against the same file is safe — records are upserted, not duplicated.

Preview rendering requires Microsoft PowerPoint (Windows COM) or LibreOffice. If neither is available, pass `--no-preview`.

### `status` — Show library statistics

```bash
python -m slidestein status
```

Prints counts of indexed decks, slides, previews, classified slides, and embedding-equipped slides, plus a per-deck breakdown table.

### `generate` — Generate a slide *(not yet implemented)*

```bash
python -m slidestein generate "A 2x2 matrix comparing cost vs. impact"
```

End-to-end generation pipeline — not yet fully implemented.

## Running tests

```bash
# Unit tests only (no rendering backend required)
.\.venv\Scripts\python.exe -m pytest tests/ -m "not integration" -q

# Include integration tests (requires PowerPoint or LibreOffice)
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

## Project layout

```
src/slidestein/
    cli.py              CLI entry point (Typer)
    config.py           Pydantic Settings
    domain/models.py    All Pydantic pipeline models
    library/store.py    SQLite slide library
    pptx/
        adapter.py      PPTMasterAdapter ABC
        python_pptx_adapter.py  Production adapter (python-pptx + COM/LibreOffice)
        stub.py         Stub adapter (testing / scaffold)
    ingestion/service.py  Deck ingestion service
    pipeline.py         9-stage generation pipeline skeleton
data/
    slidestein.db       SQLite database
    previews/           PNG previews ({fingerprint[:12]}/{slide_number:03d}.png)
    test_decks/         Sample PPTX files for development
```
