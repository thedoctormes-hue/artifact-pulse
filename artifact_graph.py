#!/usr/bin/env python3
"""
artifact_graph.py — визуализация графа артефактов LabDoctorM.

Генерирует:
- DOT формат для Graphviz (SVG/PNG)
- JSON для D3.js визуализации
- HTML страницу с интерактивным графом
- Текстовую статистику графа

Usage:
  python3 artifact_graph.py [--format dot|json|html|text] [--output FILE] [--min-links N]
"""

import sys
import os
import re
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
from config_loader import get_lab_dir, get_artifact_dirs
from artifact_core import parse_frontmatter, load_all_artifacts as _canonical_load_all

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()

ID_PATTERN = re.compile(r"\b([A-Z]{2,4}-\d{3,4})\b")
TEMPLATE_NAMES = {"template", "шаблон", "readme"}

STATUS_COLORS = {
    "active": "#4CAF50",
    "accepted": "#2196F3",
    "proposed": "#FF9800",
    "draft": "#9E9E9E",
    "pending": "#9E9E9E",
    "archived": "#795548",
    "rejected": "#F44336",
    "deprecated": "#F44336",
    "stale": "#FF5722",
    "consolidated": "#00BCD4",
    "new": "#CDDC39",
    "unknown": "#9E9E9E",
}

TYPE_SHAPES = {
    "pattern": "box",
    "adr": "ellipse",
    "rule": "diamond",
    "spec": "note",
    "incident": "octagon",
    "metric": "hexagon",
    "backlog": "folder",
}


def _adapt_for_graph(raw: dict) -> dict:
    """Adapt canonical artifact format to graph module's expected structure."""
    artifacts = {}
    for aid, art in raw.items():
        artifacts[aid] = {
            "id": art["id"],
            "type": art["type"],
            "title": art["title"][:60],
            "status": art["status"],
            "file": art["file"],
            "tags": art.get("tags", []),
            "confirmations": int(art["meta"].get("confirmations", 0) or 0),
            "full_content": art["full_content"],
        }
    return artifacts


def load_artifacts() -> dict:
    raw = _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)
    return _adapt_for_graph(raw)


def build_graph(artifacts: dict) -> dict:
    all_ids = set(artifacts.keys())
    outbound = defaultdict(set)
    inbound = defaultdict(set)

    for aid, art in artifacts.items():
        links = set()
        for m in ID_PATTERN.finditer(art["full_content"]):
            links.add(m.group(1))
        links.discard(aid)
        valid = links & all_ids
        outbound[aid] = valid
        for t in valid:
            inbound[t].add(aid)

    return {
        "nodes": artifacts,
        "outbound": {k: list(v) for k, v in outbound.items()},
        "inbound": {k: list(v) for k, v in inbound.items()},
    }


def generate_dot(graph: dict, min_links: int = 0) -> str:
    lines = ["digraph artifacts {", '  rankdir=LR;', '  node [fontname="sans-serif", fontsize=10];', ""]

    # Nodes
    for aid, art in graph["nodes"].items():
        total_links = len(graph["outbound"].get(aid, [])) + len(graph["inbound"].get(aid, []))
        if total_links < min_links:
            continue

        color = STATUS_COLORS.get(art["status"], "#9E9E9E")
        shape = TYPE_SHAPES.get(art["type"], "box")
        label = f"{aid}\\n{art['title'][:40]}"
        tooltip = f"{art['title']} ({art['status']})"

        lines.append(f'  "{aid}" [label="{label}", shape={shape}, color="{color}", tooltip="{tooltip}"];')

    lines.append("")

    # Edges
    seen_edges = set()
    for aid, targets in graph["outbound"].items():
        for t in targets:
            edge = (aid, t)
            if edge not in seen_edges:
                lines.append(f'  "{aid}" -> "{t}";')
                seen_edges.add(edge)

    lines.append("}")
    return "\n".join(lines)


def generate_json(graph: dict) -> dict:
    nodes = []
    for aid, art in graph["nodes"].items():
        nodes.append({
            "id": aid,
            "type": art["type"],
            "title": art["title"],
            "status": art["status"],
            "file": art["file"],
            "tags": art["tags"],
            "confirmations": art["confirmations"],
            "inbound": len(graph["inbound"].get(aid, [])),
            "outbound": len(graph["outbound"].get(aid, [])),
        })

    links = []
    seen = set()
    for aid, targets in graph["outbound"].items():
        for t in targets:
            key = (aid, t)
            if key not in seen:
                links.append({"source": aid, "target": t})
                seen.add(key)

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "total_nodes": len(nodes),
        "total_links": len(links),
        "nodes": nodes,
        "links": links,
    }


def generate_html(graph: dict) -> str:
    data = generate_json(graph)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>LabDoctorM — Artifact Graph</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
body {{ margin: 0; font-family: sans-serif; background: #1a1a2e; color: #eee; }}
#graph {{ width: 100vw; height: 100vh; }}
.controls {{ position: fixed; top: 10px; left: 10px; background: #16213e; padding: 15px; border-radius: 8px; max-width: 300px; }}
.controls h2 {{ margin: 0 0 10px 0; font-size: 14px; color: #e94560; }}
.controls label {{ display: block; margin: 5px 0; font-size: 12px; }}
.controls select {{ width: 100%; padding: 4px; background: #0f3460; color: #eee; border: 1px solid #e94560; border-radius: 4px; }}
.stats {{ position: fixed; bottom: 10px; left: 10px; background: #16213e; padding: 10px; border-radius: 8px; font-size: 12px; }}
.node text {{ fill: #eee; font-size: 9px; pointer-events: none; }}
.link {{ stroke: #444; stroke-opacity: 0.6; }}
</style>
</head>
<body>
<div class="controls">
  <h2>🔬 Artifact Graph</h2>
  <label>Filter by type:
    <select id="typeFilter" onchange="filterGraph()">
      <option value="all">All</option>
      <option value="adr">ADR</option>
      <option value="pattern">Patterns</option>
      <option value="rule">Rules</option>
      <option value="spec">Specs</option>
      <option value="incident">Incidents</option>
      <option value="metric">Metrics</option>
    </select>
  </label>
  <label>Filter by status:
    <select id="statusFilter" onchange="filterGraph()">
      <option value="all">All</option>
      <option value="active">Active</option>
      <option value="accepted">Accepted</option>
      <option value="proposed">Proposed</option>
      <option value="archived">Archived</option>
    </select>
  </label>
</div>
<div class="stats" id="stats"></div>
<svg id="graph"></svg>
<script>
const data = {json.dumps(data, ensure_ascii=False)};

const svg = d3.select("#graph");
const width = window.innerWidth;
const height = window.innerHeight;
svg.attr("width", width).attr("height", height);

const colorMap = {json.dumps(STATUS_COLORS)};

const simulation = d3.forceSimulation(data.nodes)
  .force("link", d3.forceLink(data.links).id(d => d.id).distance(80))
  .force("charge", d3.forceManyBody().strength(-200))
  .force("center", d3.forceCenter(width / 2, height / 2));

const link = svg.append("g").selectAll("line")
  .data(data.links).enter().append("line")
  .attr("class", "link")
  .attr("stroke-width", 1);

const node = svg.append("g").selectAll("g")
  .data(data.nodes).enter().append("g")
  .call(d3.drag()
    .on("start", (e, d) => {{ if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on("drag", (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
    .on("end", (e, d) => {{ if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }}));

node.append("circle")
  .attr("r", d => 5 + Math.sqrt(d.inbound + d.outbound) * 2)
  .attr("fill", d => colorMap[d.status] || "#9E9E9E")
  .attr("stroke", "#fff").attr("stroke-width", 0.5);

node.append("text")
  .attr("dx", 8).attr("dy", 3)
  .text(d => d.id);

node.append("title").text(d => `${{d.id}}: ${{d.title}} (${{d.status}})`);

simulation.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
}});

document.getElementById("stats").innerHTML =
  `<strong>Nodes:</strong> ${{data.nodes.length}} | <strong>Links:</strong> ${{data.links.length}}`;

function filterGraph() {{
  const type = document.getElementById("typeFilter").value;
  const status = document.getElementById("statusFilter").value;
  node.style("display", d => {{
    if (type !== "all" && d.type !== type) return "none";
    if (status !== "all" && d.status !== status) return "none";
    return null;
  }});
}}
</script>
</body>
</html>"""


def generate_text_stats(graph: dict) -> str:
    nodes = graph["nodes"]
    outbound = graph["outbound"]
    inbound = graph["inbound"]

    total = len(nodes)
    total_links = sum(len(t) for t in outbound.values())

    # Count by type
    by_type = defaultdict(int)
    by_status = defaultdict(int)
    for art in nodes.values():
        by_type[art["type"]] += 1
        by_status[art["status"]] += 1

    # Find orphans
    orphans = [aid for aid in nodes if not inbound.get(aid) and not outbound.get(aid)]
    # Find hubs (most referenced)
    hubs = sorted([(aid, len(inbound.get(aid, []))) for aid in nodes], key=lambda x: x[1], reverse=True)[:5]

    lines = [
        "═══ ARTIFACT GRAPH STATS ═══",
        f"Total nodes: {total}",
        f"Total links: {total_links}",
        f"Avg links per node: {round(total_links / max(total, 1), 1)}",
        f"Isolated nodes: {len(orphans)}",
        "",
        "── By Type ──",
    ]
    for t, c in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"  {t}: {c}")

    lines.append("")
    lines.append("── By Status ──")
    for s, c in sorted(by_status.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"  {s}: {c}")

    lines.append("")
    lines.append("── Hubs (most referenced) ──")
    for aid, count in hubs:
        art = nodes[aid]
        lines.append(f"  {aid}: {count} inbound — {art['title'][:50]}")

    if orphans:
        lines.append("")
        lines.append("── Isolated Nodes ──")
        for aid in orphans[:10]:
            lines.append(f"  {aid}: {nodes[aid]['title'][:50]}")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Artifact graph visualization")
    parser.add_argument("--format", choices=["dot", "json", "html", "text"], default="text")
    parser.add_argument("--output", type=str, help="Output file path")
    parser.add_argument("--min-links", type=int, default=0, help="Min links to include node")
    args = parser.parse_args()

    artifacts = load_artifacts()
    graph = build_graph(artifacts)

    if args.format == "dot":
        output = generate_dot(graph, args.min_links)
    elif args.format == "json":
        output = json.dumps(generate_json(graph), ensure_ascii=False, indent=2)
    elif args.format == "html":
        output = generate_html(graph)
    else:
        output = generate_text_stats(graph)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Output saved: {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
