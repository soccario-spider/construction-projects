# Construction Skills MCP Connector

An MCP server that exposes this repo's shared, deterministic building
blocks — PDF/vision tooling, the findings graph, the issue registry, the
skill catalog, and the `reference/` domain data — as MCP tools, so any
MCP-capable client (not just Claude Code driving a `SKILL.md` workflow) can
call them directly.

It does **not** wrap every per-skill script. Skills like `bid-tabulator` or
`subcontract-writer` encode a workflow (a `SKILL.md` SOP), not a single
deterministic call — those stay skills, driven by Claude following their
SOP. This server covers the general-purpose tooling in `scripts/` that
those SOPs already call into, plus read access to `reference/`.

## What it exposes

**Catalog**
- `list_skills` — name, description, argument hint for every production skill
- `list_reference_files` / `read_reference_file` — CSI MasterFormat, drawing
  conventions, abbreviations, scale factors, ADA requirements, IBC egress
  tables, issue-type patterns

**PDF / vision** (`scripts/pdf/`, `scripts/vision/`)
- `rasterize_pdf_page`, `crop_image_region`, `extract_pdf_text_region`,
  `extract_pdf_annotations`, `annotate_pdf`, `analyze_title_block`

**RFI** (`scripts/rfi/`)
- `generate_rfi_pdf`

**Findings graph** (`scripts/graph/`, `scripts/bulk/`)
- `write_finding`, `query_findings`, `consolidate_extraction`

**Issue registry** (`scripts/issue_manager.py`)
- `add_issue`, `list_issues`, `get_issue`, `update_issue`, `issue_stats`

Most tools take an optional `project_dir` argument — the *construction
project* being worked on (the one with a `.construction/` directory), not
this skills repo. It defaults to the server process's working directory.

## Setup

```bash
./setup            # installs mcp_server/requirements.txt into the shared venv
```

This repo ships a project-scoped `.mcp.json` pointing at
`bin/construction-python mcp_server/server.py`, so Claude Code picks the
server up automatically when you open this repo (or any project that
imports it) — no manual registration needed. If your MCP client doesn't
read `.mcp.json`, point it at the same command directly:

```json
{
  "mcpServers": {
    "construction-skills": {
      "command": "bin/construction-python",
      "args": ["mcp_server/server.py"]
    }
  }
}
```

## Run standalone

```bash
bin/construction-python mcp_server/server.py
```

Speaks MCP over stdio.
