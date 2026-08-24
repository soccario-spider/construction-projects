#!/usr/bin/env python3
"""
Construction Skills MCP server.

Exposes this repo's shared, deterministic building blocks — the PDF/vision
scripts in scripts/, the findings graph, the issue registry, the skill
catalog, and the reference data in reference/ — as MCP tools and resources.

This lets any MCP-capable client (Claude Code with an .mcp.json entry,
Claude Desktop, other agent hosts) call the same operations the skills use
internally, without having to invoke a full SKILL.md workflow.

It does NOT wrap every per-skill script — those are workflow-specific and
meant to be driven by a skill's SOP. This server covers the general-purpose
tooling in scripts/ plus read access to reference/.

Run directly:
    bin/construction-python mcp_server/server.py

Most tools accept an optional `project_dir` argument. That's the
construction project being worked on (the one with a `.construction/`
directory) — NOT this skills repo. It defaults to the server process's
current working directory.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
REFERENCE_DIR = REPO_ROOT / "reference"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
PYTHON_WRAPPER = REPO_ROOT / "bin" / "construction-python"

mcp = FastMCP("construction-skills")


# --- internals ---------------------------------------------------------

def _python_cmd() -> list[str]:
    """Prefer the project's managed venv (bin/construction-python); fall
    back to whatever Python is running this server."""
    if PYTHON_WRAPPER.exists() and os.access(PYTHON_WRAPPER, os.X_OK):
        return [str(PYTHON_WRAPPER)]
    return [sys.executable]


def _resolve_project_dir(project_dir: Optional[str]) -> Path:
    return Path(project_dir).expanduser().resolve() if project_dir else Path.cwd()


def _run(script: Path, args: list[str], cwd: Optional[Path] = None) -> str:
    """Run a shared script and return its stdout. Raises on non-zero exit."""
    cmd = _python_cmd() + [str(script), *args]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None
    )
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise RuntimeError(f"{script.name} failed (exit {result.returncode}):\n{detail}")
    return result.stdout.strip() or result.stderr.strip()


def _resolve_within(base: Path, name: str) -> Path:
    """Resolve `name` under `base`, refusing to escape it."""
    candidate = (base / name).resolve()
    base_resolved = base.resolve()
    if base_resolved not in candidate.parents and candidate != base_resolved:
        raise ValueError(f"'{name}' is outside {base}")
    return candidate


# --- catalog tools -------------------------------------------------------

@mcp.tool()
def list_skills() -> str:
    """List every production construction skill (name, description,
    argument hint) parsed from each skill's SKILL.md front matter. Skips
    dev-only (`_dev/`) and deprecated (`_deprecated_*`) skills."""
    import yaml

    skills = []
    if not SKILLS_DIR.is_dir():
        return json.dumps(skills)

    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        skill_name = skill_md.parent.name
        if skill_name.startswith("_deprecated_") or skill_name.startswith("_"):
            continue
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        front_matter = yaml.safe_load(text[3:end]) or {}
        skills.append(
            {
                "name": front_matter.get("name", skill_name),
                "description": front_matter.get("description", "").strip(),
                "argument_hint": front_matter.get("argument-hint"),
                "path": str(skill_md.relative_to(REPO_ROOT)),
            }
        )
    return json.dumps(skills, indent=2)


@mcp.tool()
def list_reference_files() -> str:
    """List the shared domain-knowledge files under reference/ (CSI
    MasterFormat, drawing conventions, abbreviations, scale factors, ADA
    requirements, IBC egress tables, issue-type patterns) with their sizes.
    Use read_reference_file to fetch one."""
    files = []
    for path in sorted(REFERENCE_DIR.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": str(path.relative_to(REFERENCE_DIR)),
                    "bytes": path.stat().st_size,
                }
            )
    return json.dumps(files, indent=2)


@mcp.tool()
def read_reference_file(path: str) -> str:
    """Read one file from reference/ by its relative path (as returned by
    list_reference_files), e.g. "csi_masterformat.yaml" or
    "ada_requirements.yaml"."""
    target = _resolve_within(REFERENCE_DIR, path)
    if not target.is_file():
        raise FileNotFoundError(f"No such reference file: {path}")
    return target.read_text(encoding="utf-8")


# --- PDF / vision tools ----------------------------------------------------

@mcp.tool()
def rasterize_pdf_page(
    pdf_path: str,
    page: int,
    dpi: int = 200,
    output: str = "page.png",
    crop: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> str:
    """Rasterize one page of a construction PDF to a PNG for vision reading.
    Construction sheets are large-format (30"x42") — never read a PDF
    directly, always rasterize first. `page` is 1-based. `crop` is an
    optional "x1,y1,x2,y2" region in percentages (0-100)."""
    args = [pdf_path, str(page), "--dpi", str(dpi), "--output", output]
    if crop:
        args += ["--crop", crop]
    return _run(SCRIPTS_DIR / "pdf" / "rasterize_page.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def crop_image_region(
    image_path: str,
    output: str = "cropped.png",
    anchor: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    box: Optional[str] = None,
    normalized: bool = False,
    padding: int = 0,
    project_dir: Optional[str] = None,
) -> str:
    """Crop a region out of a rasterized sheet image. Either give an
    `anchor` ("bottom-right"|"bottom-left"|"top-right"|"top-left"|"center")
    with `width`/`height`, or give an explicit `box` as "x1,y1,x2,y2"
    (pixels, or 0-1 if `normalized=True` — use normalized coordinates from
    graph centroids/bounding regions)."""
    args = [image_path, "--output", output]
    if anchor:
        args += ["--anchor", anchor]
    if width is not None:
        args += ["--width", str(width)]
    if height is not None:
        args += ["--height", str(height)]
    if box:
        args += ["--box", box]
    if normalized:
        args.append("--normalized")
    if padding:
        args += ["--padding", str(padding)]
    return _run(SCRIPTS_DIR / "pdf" / "crop_region.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def extract_pdf_text_region(
    pdf_path: str,
    page: int,
    bbox: Optional[str] = None,
    output: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> str:
    """Extract text (and layout) from a PDF page, optionally restricted to
    a `bbox` "x1,y1,x2,y2" in PDF points. `page` is 1-based."""
    args = [pdf_path, str(page)]
    if bbox:
        args += ["--bbox", bbox]
    if output:
        args += ["--output", output]
    return _run(SCRIPTS_DIR / "pdf" / "extract_text_region.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def extract_pdf_annotations(
    pdf_path: str,
    output: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> str:
    """Extract markup annotations (clouds, comments, stamps) already present
    in a PDF, e.g. a markup set returned by a reviewer."""
    args = [pdf_path]
    if output:
        args += ["--output", output]
    return _run(SCRIPTS_DIR / "pdf" / "extract_annotations.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def annotate_pdf(
    pdf_path: str,
    items_json_path: str,
    output: Optional[str] = None,
    author: str = "Claude Code",
    project_dir: Optional[str] = None,
) -> str:
    """Write markup annotations onto a PDF (viewable in Bluebeam/Adobe) from
    a JSON file of annotation items."""
    args = ["--pdf", pdf_path, "--items", items_json_path, "--author", author]
    if output:
        args += ["--output", output]
    return _run(SCRIPTS_DIR / "pdf" / "annotate_pdf.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def analyze_title_block(
    pdf_path: str,
    page: int = 1,
    output: str = "title_block.png",
    dpi: int = 200,
    project_dir: Optional[str] = None,
) -> str:
    """Crop the title block region (bottom-right) from a drawing sheet PDF
    page for reading project name, sheet number, scale, and revisions."""
    args = [pdf_path, "--page", str(page), "--output", output, "--dpi", str(dpi)]
    return _run(SCRIPTS_DIR / "vision" / "analyze_title_block.py", args, _resolve_project_dir(project_dir))


# --- RFI tool --------------------------------------------------------------

@mcp.tool()
def generate_rfi_pdf(
    data_json_path: str,
    output_path: str,
    markup_pdf: Optional[str] = None,
    log_xlsx: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> str:
    """Render a formal RFI PDF from a structured RFI data JSON file
    (see the rfi-drafter skill's references/rfi-format.md for the schema),
    optionally merging a markup PDF and updating an RFI log workbook."""
    args = ["--data", data_json_path, "--output", output_path]
    if markup_pdf:
        args += ["--markup", markup_pdf]
    if log_xlsx:
        args += ["--log", log_xlsx]
    return _run(SCRIPTS_DIR / "rfi" / "generate_rfi_pdf.py", args, _resolve_project_dir(project_dir))


# --- findings graph tools ----------------------------------------------

@mcp.tool()
def write_finding(
    finding_type: str,
    title: str,
    data: Optional[str] = None,
    source_sheet: Optional[str] = None,
    source_sheets: Optional[str] = None,
    output_file: Optional[str] = None,
    output_files: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> str:
    """Write a structured finding to the project's
    .construction/agent_findings/ graph. `data` is a JSON object string;
    `source_sheets`/`output_files` are JSON array strings."""
    args = ["--type", finding_type, "--title", title]
    if data:
        args += ["--data", data]
    if source_sheet:
        args += ["--source-sheet", source_sheet]
    if source_sheets:
        args += ["--source-sheets", source_sheets]
    if output_file:
        args += ["--output-file", output_file]
    if output_files:
        args += ["--output-files", output_files]
    return _run(SCRIPTS_DIR / "graph" / "write_finding.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def query_findings(
    type: Optional[str] = None,
    sheet: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 20,
    project_dir: Optional[str] = None,
) -> str:
    """Query prior findings written to the project's
    .construction/agent_findings/ graph, filtered by finding type, source
    sheet, and/or date (YYYY-MM-DD). Returns JSON."""
    args = []
    if type:
        args += ["--type", type]
    if sheet:
        args += ["--sheet", sheet]
    if since:
        args += ["--since", since]
    args += ["--limit", str(limit)]
    return _run(SCRIPTS_DIR / "graph" / "query_findings.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def consolidate_extraction(
    findings_dir: str,
    type: str = "sheet_extraction",
    output: str = "semantic_index.yaml",
    project_dir: Optional[str] = None,
) -> str:
    """Consolidate per-sheet extraction findings of a given type into one
    semantic index YAML file."""
    args = ["--findings-dir", findings_dir, "--type", type, "--output", output]
    return _run(SCRIPTS_DIR / "bulk" / "consolidate_extraction.py", args, _resolve_project_dir(project_dir))


# --- issue registry tools ------------------------------------------------

@mcp.tool()
def add_issue(
    source_skill: str,
    severity: str,
    description: str,
    confidence: str = "medium",
    sheets: str = "",
    spec_sections: str = "",
    rooms: str = "",
    elements: str = "",
    grid: str = "",
    context: str = "",
    rfi_subject: str = "",
    project_dir: Optional[str] = None,
) -> str:
    """Add an issue to the project's .construction/issues/ registry.
    `severity` is one of info|warning|conflict|safety. Issues accumulate
    ambient findings from any skill; they are reviewed and escalated to
    formal RFIs by the rfi-drafter skill — no skill writes an RFI directly."""
    args = [
        "add",
        "--source-skill", source_skill,
        "--severity", severity,
        "--description", description,
        "--confidence", confidence,
    ]
    if sheets:
        args += ["--sheets", sheets]
    if spec_sections:
        args += ["--spec-sections", spec_sections]
    if rooms:
        args += ["--rooms", rooms]
    if elements:
        args += ["--elements", elements]
    if grid:
        args += ["--grid", grid]
    if context:
        args += ["--context", context]
    if rfi_subject:
        args += ["--rfi-subject", rfi_subject]
    return _run(SCRIPTS_DIR / "issue_manager.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def list_issues(
    severity: Optional[str] = None,
    source_skill: Optional[str] = None,
    status: Optional[str] = None,
    include_all: bool = False,
    project_dir: Optional[str] = None,
) -> str:
    """List issues in the project's .construction/issues/ registry, filtered
    by severity, source skill, and/or status. By default only open issues
    are shown; set include_all=True to include resolved/dismissed ones."""
    args = ["list"]
    if severity:
        args += ["--severity", severity]
    if source_skill:
        args += ["--source-skill", source_skill]
    if status:
        args += ["--status", status]
    if include_all:
        args.append("--all")
    return _run(SCRIPTS_DIR / "issue_manager.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def get_issue(issue_id: str, project_dir: Optional[str] = None) -> str:
    """Fetch one issue from the project's .construction/issues/ registry by
    its ID (e.g. "ISS-2026-0001")."""
    return _run(
        SCRIPTS_DIR / "issue_manager.py", ["get", "--id", issue_id], _resolve_project_dir(project_dir)
    )


@mcp.tool()
def update_issue(
    issue_id: str,
    status: Optional[str] = None,
    rfi_number: Optional[str] = None,
    resolution_notes: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> str:
    """Update an issue's status in the project's .construction/issues/
    registry. `status` is one of open|reviewed|escalated|resolved|dismissed.
    Set `rfi_number` when escalating; set `resolution_notes` when
    resolving/dismissing."""
    args = ["update", "--id", issue_id]
    if status:
        args += ["--status", status]
    if rfi_number:
        args += ["--rfi-number", rfi_number]
    if resolution_notes:
        args += ["--resolution-notes", resolution_notes]
    return _run(SCRIPTS_DIR / "issue_manager.py", args, _resolve_project_dir(project_dir))


@mcp.tool()
def issue_stats(project_dir: Optional[str] = None) -> str:
    """Summary statistics (counts by status, severity, source skill) for
    the project's .construction/issues/ registry."""
    return _run(SCRIPTS_DIR / "issue_manager.py", ["stats"], _resolve_project_dir(project_dir))


if __name__ == "__main__":
    mcp.run()
