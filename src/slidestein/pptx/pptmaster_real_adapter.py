"""PPTMasterRealAdapter — drives PPT Master via subprocess for native PPTX roundtrip.

Architecture contract:
  - NEVER import PPT Master modules directly.
  - NEVER reimplement PPT Master's roundtrip logic with python-pptx.
  - Invoke ppt-master ONLY via subprocess through its documented CLI.
  - Surface all ppt-master failures as PPTMasterError.

PPT Master workflow used (Edit Native PPTX route):
  Import:  pptx-to-svg <deck> -o <workspace> --inheritance-mode both --roundtrip
  Export:  svg-to-pptx <workspace> --roundtrip -o <output.pptx>
  Refresh: svg-authoring-view <workspace>/authoring-svg-flat --refresh-summary
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from slidestein.domain.models import ContentSlot, SlideMetadata
from slidestein.pptx.adapter import PPTMasterAdapter


class PPTMasterError(RuntimeError):
    """Raised when ppt-master reports an unrecoverable failure."""


def _find_pptmaster_cli(python: Path) -> Path:
    """Return the path to ppt-master's cli.py installed alongside *python*.

    ppt-master installs cli.py as a top-level py-module into the venv's
    site-packages.  The layout differs between Windows (Lib/site-packages)
    and Unix (lib/pythonX.Y/site-packages).
    """
    candidates = [
        python.parent.parent / "Lib" / "site-packages" / "cli.py",  # Windows venv
        python.parent.parent / "lib" / "site-packages" / "cli.py",  # Unix flat venv
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fall back: ask the interpreter where it installed cli
    result = subprocess.run(
        [str(python), "-c", "import cli, os; print(os.path.abspath(cli.__file__))"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        path = Path(result.stdout.strip())
        if path.exists():
            return path
    raise FileNotFoundError(
        f"Cannot locate ppt-master cli.py for Python at {python}. "
        "Install ppt-master: uv pip install ppt-master "
        "--python tools/pptmaster-env/Scripts/python.exe"
    )


def _replace_text_in_svg(svg_path: Path, replacements: dict[str, str]) -> None:
    """Apply literal string replacements inside an SVG file.

    Replacements are applied to the raw file text, so both element content
    and attribute values are matched.  Keys are matched in insertion order;
    earlier replacements do not affect later matches on the same byte range.
    """
    content = svg_path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        if old:
            content = content.replace(old, new)
    svg_path.write_text(content, encoding="utf-8")


class PPTMasterRealAdapter(PPTMasterAdapter):
    """PPTMasterAdapter implementation that drives PPT Master via subprocess.

    Requires a separate ppt-master installation at tools/pptmaster-env/.
    Use PPTMasterRealAdapter.from_auto_discover() for the standard layout, or
    pass explicit paths to the constructor.

    render_preview delegates to PythonPptxAdapter (PowerPoint COM / LibreOffice)
    since PPT Master's Playwright renderer is not available in this environment.

    introspect_template and fill_and_export are NOT implemented here — they belong
    to the AI content-drafting pipeline (Milestone 3+).
    """

    def __init__(
        self,
        pptmaster_python: Path,
        workspace_root: Path,
    ) -> None:
        self._python = pptmaster_python
        self._cli = _find_pptmaster_cli(pptmaster_python)
        self._workspace_root = workspace_root

    @classmethod
    def from_auto_discover(
        cls,
        workspace_root: Path | None = None,
    ) -> "PPTMasterRealAdapter":
        """Discover ppt-master from the standard tools/pptmaster-env/ location."""
        candidates = [
            Path("tools/pptmaster-env/Scripts/python.exe"),  # Windows
            Path("tools/pptmaster-env/bin/python"),           # Unix/macOS
        ]
        for c in candidates:
            if c.exists():
                return cls(
                    pptmaster_python=c,
                    workspace_root=workspace_root or Path("outputs/workspaces"),
                )
        raise FileNotFoundError(
            "ppt-master venv not found at tools/pptmaster-env/. "
            "Create it: uv venv tools/pptmaster-env --python <approved-python> "
            "then: uv pip install ppt-master --python tools/pptmaster-env/Scripts/python.exe"
        )

    @classmethod
    def from_settings(cls, settings: object) -> "PPTMasterRealAdapter":
        """Construct from a Settings object (uses pptmaster_python if set)."""
        python = getattr(settings, "pptmaster_python", None)
        workspace_root = getattr(settings, "pptmaster_workspace_root", None) or Path(
            "outputs/workspaces"
        )
        if python:
            return cls(pptmaster_python=Path(python), workspace_root=Path(workspace_root))
        return cls.from_auto_discover(workspace_root=Path(workspace_root))

    # ------------------------------------------------------------------
    # Base adapter interface
    # ------------------------------------------------------------------

    def introspect_template(self, template_path: Path) -> SlideMetadata:
        raise NotImplementedError(
            "PPTMasterRealAdapter.introspect_template is not yet implemented. "
            "Use PythonPptxAdapter for template introspection."
        )

    def fill_and_export(
        self,
        template_path: Path,
        slots: list[ContentSlot],
        output_path: Path,
    ) -> Path:
        raise NotImplementedError(
            "PPTMasterRealAdapter.fill_and_export requires the content-drafting pipeline "
            "(Milestone 3+).  For roundtrip operations use extract_slide / replace_text_in_slide."
        )

    def render_preview(
        self,
        pptx_path: Path,
        slide_number: int,
        output_path: Path,
    ) -> Path:
        """Delegate PNG rendering to PythonPptxAdapter (COM / LibreOffice)."""
        from slidestein.pptx.python_pptx_adapter import PythonPptxAdapter

        return PythonPptxAdapter().render_preview(pptx_path, slide_number, output_path)

    # ------------------------------------------------------------------
    # Roundtrip operations
    # ------------------------------------------------------------------

    def extract_slide(
        self,
        source_pptx: Path,
        slide_number: int,
        output_path: Path,
    ) -> Path:
        """Extract a single slide using PPT Master's native roundtrip route.

        Unchanged slides pass through with their original OOXML relationships
        preserved byte-for-byte.  Shapes, charts, tables, and SmartArt remain
        natively editable in PowerPoint.
        """
        workspace = self._import_deck(source_pptx, force_reimport=False)
        self._write_page_plan(workspace, [slide_number])
        return self._export_pptx(workspace, output_path)

    def replace_text_in_slide(
        self,
        source_pptx: Path,
        slide_number: int,
        replacements: dict[str, str],
        output_path: Path,
    ) -> Path:
        """[SVG FALLBACK] Replace text via PPT Master's SVG roundtrip route.

        This is the FALLBACK editing path.  For ordinary text replacement prefer
        PowerPointComEditor.replace_text() (native COM) which preserves all
        run-level formatting and complex objects without rebuilding the slide.

        Use this SVG path only when:
          - Microsoft PowerPoint COM is not available.
          - Structural or template-level modifications require SVG editing.

        The modified slide is rebuilt from the edited SVG.  Unmodified objects
        retain their native PPT backing where PPT Master supports passthrough,
        but complex effects may be approximated rather than reproduced exactly.
        """
        workspace = self._import_deck(source_pptx, force_reimport=True)
        svg_name = f"slide_{slide_number:02d}.svg"
        svg_path = workspace / "authoring-svg-flat" / svg_name
        if not svg_path.exists():
            raise PPTMasterError(
                f"SVG for slide {slide_number} not found at {svg_path}. "
                "The pptx-to-svg import may have failed silently."
            )
        _replace_text_in_svg(svg_path, replacements)
        self._refresh_authoring_summary(workspace)
        self._write_page_plan(workspace, [slide_number])
        return self._export_pptx(workspace, output_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
        cmd = [str(self._python), str(self._cli), *args]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _import_deck(self, source_pptx: Path, *, force_reimport: bool) -> Path:
        """Run pptx-to-svg --roundtrip and return the workspace path.

        Skips re-import when the workspace already holds the same source deck
        (compared by file size) AND force_reimport is False.
        """
        workspace = self._workspace_root / source_pptx.stem
        source_copy = workspace / "sources" / "source.pptx"

        if (
            not force_reimport
            and source_copy.exists()
            and source_copy.stat().st_size == source_pptx.stat().st_size
            and (workspace / "authoring-svg-flat").exists()
        ):
            return workspace

        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        # Do NOT pre-create workspace itself — ppt-master uses an atomic
        # rename (temp-dir → workspace) that fails if the target already exists.

        result = self._run(
            "pptx-to-svg",
            str(source_pptx.resolve()),
            "-o", str(workspace.resolve()),
            "--inheritance-mode", "both",
            "--roundtrip",
        )

        authoring_dir = workspace / "authoring-svg-flat"
        if not authoring_dir.exists() or not any(authoring_dir.glob("slide_*.svg")):
            raise PPTMasterError(
                f"pptx-to-svg failed to create the authoring workspace at {workspace}.\n"
                f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
            )
        return workspace

    def _write_page_plan(self, workspace: Path, slide_numbers: list[int]) -> None:
        """Write page_plan.json selecting the given source slides."""
        plan = {
            "schema": "ppt-master.roundtrip-page-plan.v1",
            "pages": [{"source_slide": n} for n in slide_numbers],
        }
        (workspace / "page_plan.json").write_text(
            json.dumps(plan, indent=2), encoding="utf-8"
        )

    def _refresh_authoring_summary(self, workspace: Path) -> None:
        """Run svg-authoring-view --refresh-summary after editing SVGs."""
        self._run(
            "svg-authoring-view",
            str((workspace / "authoring-svg-flat").resolve()),
            "--refresh-summary",
        )

    def _export_pptx(self, workspace: Path, output_path: Path) -> Path:
        """Run svg-to-pptx --roundtrip and return the output PPTX path."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = self._run(
            "svg-to-pptx",
            str(workspace.resolve()),
            "--roundtrip",
            "-o", str(output_path.resolve()),
        )
        if not output_path.exists():
            raise PPTMasterError(
                f"svg-to-pptx failed to produce output at {output_path}.\n"
                f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
            )
        return output_path
