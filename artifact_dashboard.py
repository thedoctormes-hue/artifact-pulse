#!/usr/bin/env python3
"""
artifact_dashboard.py — HTML-дашборд здоровья артефактов LabDoctorM.

Агрегирует данные из всех модулей в единый HTML-отчёт:
- Общая статистика (количество по типам, статусам)
- Health score (0-100)
- Топ артефактов по цитированию
- Артефакты, требующие внимания (stale, broken links, low confidence)
- Граф зависимостей (D3.js)

Usage:
  python3 artifact_dashboard.py [--output FILE] [--open]
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from config_loader import get_lab_dir, get_artifact_dirs
from artifact_core import load_all_artifacts as _canonical_load_all
from artifact_constants import (
    DEFAULT_STALE_DAYS,
)

LAB_DIR = get_lab_dir()
ARTIFACT_DIRS = get_artifact_dirs()


def load_all_artifacts() -> dict:
    return _canonical_load_all(ARTIFACT_DIRS, LAB_DIR)


def _compute_type_distribution(artifacts: dict) -> dict[str, int]:
    dist: dict[str, int] = {}
    for art in artifacts.values():
        t = art.get("type", "unknown")
        dist[t] = dist.get(t, 0) + 1
    return dict(sorted(dist.items(), key=lambda x: -x[1]))


def _compute_status_distribution(artifacts: dict) -> dict[str, int]:
    dist: dict[str, int] = {}
    for art in artifacts.values():
        s = art.get("meta", {}).get("status", "unknown")
        dist[s] = dist.get(s, 0) + 1
    return dict(sorted(dist.items(), key=lambda x: -x[1]))


def _compute_confidence_distribution(artifacts: dict) -> dict[str, int]:
    dist: dict[str, int] = {}
    for art in artifacts.values():
        c = art.get("meta", {}).get("confidence", "unknown")
        dist[c] = dist.get(c, 0) + 1
    return dict(sorted(dist.items(), key=lambda x: -x[1]))


def _compute_inbound_links(artifacts: dict) -> dict[str, int]:
    from artifact_constants import REF_PATTERN
    inbound: dict[str, int] = {aid: 0 for aid in artifacts}
    for aid, art in artifacts.items():
        body = art.get("body", "")
        refs = set(REF_PATTERN.findall(body))
        refs.discard(aid)
        for ref in refs:
            if ref in inbound:
                inbound[ref] += 1
    return inbound


def _top_cited(artifacts: dict, inbound: dict[str, int], n: int = 10) -> list[dict]:
    sorted_ids = sorted(inbound, key=lambda x: -inbound[x])
    result = []
    for aid in sorted_ids[:n]:
        if inbound[aid] > 0:
            result.append({
                "id": aid,
                "title": artifacts[aid].get("meta", {}).get("title", ""),
                "type": artifacts[aid].get("type", ""),
                "inbound": inbound[aid],
            })
    return result


def _needs_attention(artifacts: dict, inbound: dict[str, int]) -> list[dict]:
    """Artifacts that need review: stale, no inbound, old."""
    from artifact_aging import days_since
    attention = []
    for aid, art in artifacts.items():
        meta = art.get("meta", {})
        status = meta.get("status", "")
        updated = meta.get("updated", meta.get("created", ""))
        updated_days = days_since(updated)
        reasons = []
        if status == "stale":
            reasons.append("stale")
        if status == "active" and updated_days > DEFAULT_STALE_DAYS and inbound.get(aid, 0) == 0:
            reasons.append(f"no updates {updated_days}d, no inbound")
        if status == "draft" and updated_days > 30:
            reasons.append(f"draft stagnant {updated_days}d")
        confidence = meta.get("confidence", "")
        if confidence in ("low", "none", ""):
            reasons.append(f"confidence: {confidence or 'unset'}")
        if reasons:
            attention.append({
                "id": aid,
                "title": meta.get("title", ""),
                "type": art.get("type", ""),
                "status": status,
                "reasons": reasons,
            })
    return sorted(attention, key=lambda x: x["id"])


def _build_graph_data(artifacts: dict) -> dict:
    """Build nodes + links for D3.js force graph."""
    from artifact_constants import REF_PATTERN, TYPE_SHAPES
    nodes = []
    for aid, art in artifacts.items():
        meta = art.get("meta", {})
        nodes.append({
            "id": aid,
            "type": art.get("type", "unknown"),
            "status": meta.get("status", "unknown"),
            "title": meta.get("title", ""),
            "shape": TYPE_SHAPES.get(art.get("type", ""), "circle"),
        })
    links = []
    for aid, art in artifacts.items():
        body = art.get("body", "")
        refs = set(REF_PATTERN.findall(body))
        refs.discard(aid)
        for ref in refs:
            if ref in artifacts:
                links.append({"source": aid, "target": ref})
    return {"nodes": nodes, "links": links}


def _compute_health_score(artifacts: dict, inbound: dict[str, int]) -> int:
    """Simple health score 0-100."""
    if not artifacts:
        return 100
    from artifact_aging import days_since
    total = len(artifacts)
    issues = 0
    for aid, art in artifacts.items():
        meta = art.get("meta", {})
        status = meta.get("status", "")
        if status in ("stale", "deprecated"):
            issues += 2
        updated = meta.get("updated", meta.get("created", ""))
        if days_since(updated) > DEFAULT_STALE_DAYS and inbound.get(aid, 0) == 0:
            issues += 1
        confidence = meta.get("confidence", "")
        if confidence in ("low", "none"):
            issues += 1
    score = max(0, 100 - (issues * 100) // (total * 3))
    return min(100, score)


def generate_dashboard(artifacts: dict, output_path: str | None = None) -> str:
    """Generate full HTML dashboard string."""
    type_dist = _compute_type_distribution(artifacts)
    status_dist = _compute_status_distribution(artifacts)
    conf_dist = _compute_confidence_distribution(artifacts)
    inbound = _compute_inbound_links(artifacts)
    top_cited = _top_cited(artifacts, inbound)
    attention = _needs_attention(artifacts, inbound)
    graph_data = _build_graph_data(artifacts)
    health = _compute_health_score(artifacts, inbound)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(artifacts)

    # Health color
    if health >= 80:
        health_color = "#22c55e"
    elif health >= 50:
        health_color = "#f59e0b"
    else:
        health_color = "#ef4444"

    graph_json = json.dumps(graph_data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Artifact Pulse — Dashboard</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }}
  .header {{ background: #1e293b; padding: 20px 30px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 1.4rem; color: #f8fafc; }}
  .header .meta {{ font-size: 0.8rem; color: #94a3b8; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; }}
  .card h3 {{ font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }}
  .stat-row {{ display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.9rem; }}
  .stat-row .label {{ color: #cbd5e1; }}
  .stat-row .value {{ color: #f8fafc; font-weight: 600; }}
  .health-score {{ font-size: 3rem; font-weight: 700; color: {health_color}; text-align: center; padding: 16px 0; }}
  .health-label {{ text-align: center; font-size: 0.8rem; color: #94a3b8; }}
  .attention-item {{ padding: 8px 0; border-bottom: 1px solid #334155; font-size: 0.85rem; }}
  .attention-item:last-child {{ border-bottom: none; }}
  .attention-id {{ color: #60a5fa; font-weight: 600; }}
  .attention-reason {{ color: #f8961e; font-size: 0.75rem; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }}
  .badge-active {{ background: #166534; color: #86efac; }}
  .badge-stale {{ background: #78350f; color: #fcd34d; }}
  .badge-archived {{ background: #374151; color: #9ca3af; }}
  .badge-draft {{ background: #1e3a5f; color: #93c5fd; }}
  .badge-deprecated {{ background: #7f1d1d; color: #fca5a5; }}
  #graph {{ width: 100%; height: 500px; background: #0f172a; border-radius: 8px; }}
  .bar {{ height: 20px; border-radius: 4px; margin: 4px 0; display: flex; align-items: center; padding: 0 8px; font-size: 0.75rem; color: #fff; }}
</style>
</head>
<body>
<div class="header">
  <h1>⚡ Artifact Pulse — Dashboard</h1>
  <div class="meta">Generated: {now} | Total artifacts: {total}</div>
</div>
<div class="container">

  <!-- Health Score -->
  <div class="grid">
    <div class="card">
      <h3>Health Score</h3>
      <div class="health-score">{health}/100</div>
      <div class="health-label">Overall system health</div>
    </div>
    <div class="card">
      <h3>By Type</h3>
      {"".join(f'<div class="stat-row"><span class="label">{t}</span><span class="value">{c}</span></div>' for t, c in type_dist.items())}
    </div>
    <div class="card">
      <h3>By Status</h3>
      {"".join(f'<div class="stat-row"><span class="label"><span class="badge badge-{s}">{s}</span></span><span class="value">{c}</span></div>' for s, c in status_dist.items())}
    </div>
    <div class="card">
      <h3>By Confidence</h3>
      {"".join(f'<div class="stat-row"><span class="label">{c or "unset"}</span><span class="value">{n}</span></div>' for c, n in conf_dist.items())}
    </div>
  </div>

  <!-- Top Cited + Attention -->
  <div class="grid">
    <div class="card">
      <h3>🏆 Top Cited</h3>
      {"".join(f'<div class="stat-row"><span class="label">{a["id"]}</span><span class="value">↑{a["inbound"]}</span></div>' for a in top_cited) if top_cited else '<div class="stat-row"><span class="label">No citations yet</span></div>'}
    </div>
    <div class="card">
      <h3>⚠️ Needs Attention ({len(attention)})</h3>
      {"".join(f'<div class="attention-item"><span class="attention-id">{a["id"]}</span> <span class="badge badge-{a["status"]}">{a["status"]}</span><br><span class="attention-reason">{", ".join(a["reasons"])}</span></div>' for a in attention[:15]) if attention else '<div class="stat-row"><span class="label">All clear ✓</span></div>'}
      {f'<div class="stat-row" style="margin-top:8px;color:#94a3b8;font-size:0.8rem;">...and {len(attention) - 15} more</div>' if len(attention) > 15 else ''}
    </div>
  </div>

  <!-- Graph -->
  <div class="card" style="margin-top: 16px;">
    <h3>Dependency Graph</h3>
    <div id="graph"></div>
  </div>

</div>

<script>
const data = {graph_json};

const svg = d3.select("#graph").append("svg")
  .attr("width", "100%")
  .attr("height", 500);

const width = document.getElementById("graph").clientWidth;
const height = 500;

svg.attr("viewBox", `0 0 ${{width}} ${{height}}`);

const colorMap = {{
  adr: "#60a5fa", pattern: "#a78bfa", rule: "#f472b6",
  backlog: "#fbbf24", incident: "#f87171", sys: "#34d399",
  report: "#fb923c", metric: "#2dd4bf", unknown: "#94a3b8"
}};

const simulation = d3.forceSimulation(data.nodes)
  .force("link", d3.forceLink(data.links).id(d => d.id).distance(60))
  .force("charge", d3.forceManyBody().strength(-150))
  .force("center", d3.forceCenter(width / 2, height / 2));

const link = svg.append("g")
  .selectAll("line")
  .data(data.links)
  .join("line")
  .attr("stroke", "#475569")
  .attr("stroke-width", 1)
  .attr("stroke-opacity", 0.5);

const node = svg.append("g")
  .selectAll("g")
  .data(data.nodes)
  .join("g")
  .call(d3.drag()
    .on("start", (event, d) => {{ if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on("drag", (event, d) => {{ d.fx = event.x; d.fy = event.y; }})
    .on("end", (event, d) => {{ if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }}));

node.append("circle")
  .attr("r", 6)
  .attr("fill", d => colorMap[d.type] || colorMap.unknown)
  .attr("stroke", d => d.status === "stale" ? "#fbbf24" : d.status === "archived" ? "#6b7280" : "#1e293b")
  .attr("stroke-width", 2);

node.append("text")
  .text(d => d.id)
  .attr("x", 8)
  .attr("y", 3)
  .attr("font-size", "9px")
  .attr("fill", "#cbd5e1");

simulation.on("tick", () => {{
  link
    .attr("x1", d => d.source.x)
    .attr("y1", d => d.source.y)
    .attr("x2", d => d.target.x)
    .attr("y2", d => d.target.y);
  node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
}});
</script>
</body>
</html>"""

    if output_path:
        Path(output_path).write_text(html, encoding="utf-8")

    return html


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Artifact Pulse Dashboard")
    parser.add_argument("--output", "-o", default=None, help="Output HTML file path")
    parser.add_argument("--open", action="store_true", help="Open in browser after generation")
    args = parser.parse_args()

    artifacts = load_all_artifacts()
    output = args.output or str(LAB_DIR / ".qwen" / "artifacts" / "dashboard.html")

    generate_dashboard(artifacts, output)
    print(f"Dashboard generated: {output}")
    print(f"Artifacts: {len(artifacts)}")

    if args.open:
        import webbrowser
        webbrowser.open(f"file://{output}")


if __name__ == "__main__":
    main()
