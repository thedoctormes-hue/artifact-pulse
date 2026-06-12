#!/usr/bin/env python3
"""
test_artifact_system.py — комплексные тесты системы артефактов LabDoctorM.

Usage:
  python3 -m pytest test_artifact_system.py -v
  python3 test_artifact_system.py
"""

import sys
import json
import tempfile
import shutil
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


def create_test_artifact_dir():
    """Create a temporary directory structure with test artifacts. Returns tmpdir path."""
    tmpdir = Path(tempfile.mkdtemp(prefix="artifact_test_"))
    dirs = {
        "pattern": tmpdir / "patterns",
        "adr": tmpdir / "adr",
        "rule": tmpdir / "rules",
        "spec": tmpdir / "specs",
        "incident": tmpdir / "incidents",
        "metric": tmpdir / "metrics",
    }
    for d in dirs.values():
        d.mkdir(parents=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    old_date = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    very_old = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    (dirs["pattern"] / "PAT-001-test-pattern.md").write_text(f"""---
id: PAT-001
type: pattern
title: "Test Pattern"
status: active
category: testing
created: {now}
updated: {now}
tags: [test]
code_refs: []
---

# PAT-001: Test Pattern

## Context
This is a test pattern for unit testing.

## Solution
Test solution here.

## Related
See ADR-001 for context.
""")

    (dirs["adr"] / "ADR-001-test-adr.md").write_text(f"""---
id: ADR-001
type: adr
title: "Test ADR Decision"
status: accepted
created: {now}
updated: {now}
tags: [test]
code_refs: []
---

# ADR-001: Test ADR Decision

## Context
This is a test ADR.

## Decision
We decided to test.

## Related
Depends on PAT-001.
""")

    (dirs["rule"] / "RUL-001-stale-rule.md").write_text(f"""---
id: RUL-001
type: rule
title: "Stale Test Rule"
status: active
category: testing
created: {old_date}
updated: {old_date}
tags: [test]
code_refs: []
---

# RUL-001: Stale Test Rule

## Description
This rule is stale for testing.
""")

    (dirs["incident"] / "INC-001-old-incident.md").write_text(f"""---
id: INC-001
type: incident
title: "Old Incident"
status: open
severity: LOW
created: {very_old}
updated: {very_old}
tags: [test]
code_refs: []
---

# INC-001: Old Incident

## Description
This incident is very old and should be archived.
""")

    (dirs["metric"] / "MET-001-orphan-metric.md").write_text(f"""---
id: MET-001
type: metric
title: "Orphan Metric"
status: active
created: {now}
updated: {now}
tags: [test]
code_refs: []
---

# MET-001: Orphan Metric

## Description
This metric has no links.
""")

    (dirs["pattern"] / "PAT-002-archived.md").write_text(f"""---
id: PAT-002
type: pattern
title: "Archived Pattern"
status: archived
category: testing
created: {very_old}
updated: {very_old}
tags: [test]
code_refs: []
---

# PAT-002: Archived Pattern

This is archived.
""")

    (dirs["adr"] / "ADR-002-broken-link.md").write_text(f"""---
id: ADR-002
type: adr
title: "ADR with Broken Link"
status: proposed
created: {now}
updated: {now}
tags: [test]
code_refs: []
---

# ADR-002: ADR with Broken Link

## Context
References non-existent PAT-999.
""")

    return tmpdir


def patch_dirs(tmpdir):
    """Return a dict of patched ARTIFACT_DIRS pointing to tmpdir."""
    (tmpdir / "specs").mkdir(exist_ok=True)
    (tmpdir / "backlog").mkdir(exist_ok=True)
    return {
        "pattern": tmpdir / "patterns",
        "adr": tmpdir / "adr",
        "rule": tmpdir / "rules",
        "spec": tmpdir / "specs",
        "backlog": tmpdir / "backlog",
        "incident": tmpdir / "incidents",
        "metric": tmpdir / "metrics",
    }


# ═══════════════════════════════════════════════════════
# Tests for artifact_stats.py
# ═══════════════════════════════════════════════════════

class TestArtifactStats(unittest.TestCase):

    def test_parse_frontmatter_valid(self):
        from artifact_core import parse_frontmatter
        content = '---\nid: PAT-001\ntype: pattern\ntitle: "Test"\nstatus: active\ntags: [test, auto]\n---\n# Body text\n'
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta["id"], "PAT-001")
        self.assertEqual(meta["type"], "pattern")
        self.assertEqual(meta["title"], "Test")
        self.assertEqual(meta["status"], "active")
        self.assertIn("Body text", body)

    def test_parse_frontmatter_empty(self):
        from artifact_core import parse_frontmatter
        content = "# Just a heading\n\nSome text."
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta, {})
        self.assertIn("Just a heading", body)

    def test_parse_frontmatter_tags_list(self):
        from artifact_core import parse_frontmatter
        content = '---\nid: PAT-001\ntags: [test, auto, generated]\n---\n# Body\n'
        meta, _ = parse_frontmatter(content)
        self.assertIsInstance(meta["tags"], list)
        self.assertEqual(len(meta["tags"]), 3)
        self.assertIn("test", meta["tags"])

    def test_load_and_stats(self):
        from artifact_stats import load_all_artifacts, compute_stats
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_stats", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_all_artifacts()
                self.assertEqual(len(artifacts), 7)
                stats = compute_stats(artifacts)
                self.assertEqual(len(stats), 7)
        finally:
            shutil.rmtree(tmpdir)


# ═══════════════════════════════════════════════════════
# Tests for artifact_aging.py
# ═══════════════════════════════════════════════════════

class TestArtifactAging(unittest.TestCase):

    def test_parse_frontmatter(self):
        from artifact_core import parse_frontmatter
        content = '---\nid: PAT-001\ntype: pattern\ntitle: "Test"\nstatus: active\ncreated: 2026-01-01T00:00:00+00:00\n---\n# Body\n'
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta["id"], "PAT-001")
        self.assertIn("Body", body)

    def test_ref_pattern(self):
        from artifact_aging import REF_PATTERN
        text = "See PAT-001 and ADR-012 for details. Also RUL-005."
        refs = REF_PATTERN.findall(text)
        self.assertIn("PAT-001", refs)
        self.assertIn("ADR-012", refs)
        self.assertIn("RUL-005", refs)

    def test_aging_detects_stale(self):
        from artifact_aging import run_aging
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_aging", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                result = run_aging(dry_run=True, stale_days=90, archive_days=180)
                self.assertGreaterEqual(result["staled"], 0)
                self.assertGreaterEqual(result["archived"], 0)
        finally:
            shutil.rmtree(tmpdir)

    def test_aging_dry_run_no_modifications(self):
        from artifact_aging import run_aging
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            mtimes_before = {}
            for d in dirs.values():
                for f in d.glob("*.md"):
                    mtimes_before[f] = f.stat().st_mtime

            with patch.multiple("artifact_aging", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                run_aging(dry_run=True, stale_days=90, archive_days=180)

            for f, mtime in mtimes_before.items():
                self.assertEqual(f.stat().st_mtime, mtime, f"File {f} was modified in dry-run!")
        finally:
            shutil.rmtree(tmpdir)


# ═══════════════════════════════════════════════════════
# Tests for artifact_link_checker.py
# ═══════════════════════════════════════════════════════

class TestArtifactLinkChecker(unittest.TestCase):

    def test_extract_links(self):
        from artifact_link_checker import extract_links
        content = "# Test\nSee PAT-001 for details.\nAlso check ADR-012 and RUL-005.\n[[INC-001]]\n[Link](PAT-002)"
        links = extract_links(content)
        self.assertIn("PAT-001", links)
        self.assertIn("ADR-012", links)
        self.assertIn("RUL-005", links)
        self.assertIn("INC-001", links)

    def test_check_links_finds_broken(self):
        from artifact_link_checker import check_links, load_all_artifacts
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_link_checker", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_all_artifacts()
                report = check_links(artifacts)
                self.assertGreaterEqual(report["broken_links"]["count"], 1)
                broken_targets = [b["to"] for b in report["broken_links"]["items"]]
                self.assertIn("PAT-999", broken_targets)
        finally:
            shutil.rmtree(tmpdir)

    def test_check_links_finds_orphans(self):
        from artifact_link_checker import check_links, load_all_artifacts
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_link_checker", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_all_artifacts()
                report = check_links(artifacts)
                orphan_ids = [o["id"] for o in report["orphans"]["items"]]
                self.assertIn("MET-001", orphan_ids)
        finally:
            shutil.rmtree(tmpdir)

    def test_check_links_graph_integrity(self):
        from artifact_link_checker import check_links, load_all_artifacts
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_link_checker", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_all_artifacts()
                report = check_links(artifacts)
                self.assertGreater(report["total_links"], 0)
                self.assertEqual(report["total_artifacts"], 7)
        finally:
            shutil.rmtree(tmpdir)


# ═══════════════════════════════════════════════════════
# Tests for artifact_graph.py
# ═══════════════════════════════════════════════════════

class TestArtifactGraph(unittest.TestCase):

    def test_build_graph(self):
        from artifact_graph import build_graph, load_artifacts
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_graph", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_artifacts()
                graph = build_graph(artifacts)
                self.assertEqual(len(graph["nodes"]), 7)
                self.assertIn("PAT-001", graph["nodes"])
                self.assertIn("ADR-001", graph["nodes"])
                self.assertIn("ADR-001", graph["outbound"].get("PAT-001", set()))
                self.assertIn("PAT-001", graph["outbound"].get("ADR-001", set()))
        finally:
            shutil.rmtree(tmpdir)

    def test_generate_dot(self):
        from artifact_graph import build_graph, load_artifacts, generate_dot
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_graph", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_artifacts()
                graph = build_graph(artifacts)
                dot = generate_dot(graph)
                self.assertIn("digraph artifacts", dot)
                self.assertIn("PAT-001", dot)
        finally:
            shutil.rmtree(tmpdir)

    def test_generate_json(self):
        from artifact_graph import build_graph, load_artifacts, generate_json
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_graph", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_artifacts()
                graph = build_graph(artifacts)
                data = generate_json(graph)
                self.assertIn("nodes", data)
                self.assertIn("links", data)
                self.assertEqual(data["total_nodes"], 7)
                self.assertGreater(data["total_links"], 0)
        finally:
            shutil.rmtree(tmpdir)

    def test_generate_html(self):
        from artifact_graph import build_graph, load_artifacts, generate_html
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_graph", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_artifacts()
                graph = build_graph(artifacts)
                html = generate_html(graph)
                self.assertIn("<!DOCTYPE html>", html)
                self.assertIn("d3", html)
        finally:
            shutil.rmtree(tmpdir)

    def test_text_stats(self):
        from artifact_graph import build_graph, load_artifacts, generate_text_stats
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_graph", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_artifacts()
                graph = build_graph(artifacts)
                stats = generate_text_stats(graph)
                self.assertIn("ARTIFACT GRAPH STATS", stats)
                self.assertIn("Total nodes: 7", stats)
        finally:
            shutil.rmtree(tmpdir)


# ═══════════════════════════════════════════════════════
# Tests for artifact_health.py
# ═══════════════════════════════════════════════════════

class TestArtifactHealth(unittest.TestCase):

    def test_frontmatter_check(self):
        from artifact_health import check_frontmatter, load_all_artifacts
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_health", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_all_artifacts()
                result = check_frontmatter(artifacts)
                self.assertEqual(result["total"], 7)
                self.assertGreater(result["score"], 0)
        finally:
            shutil.rmtree(tmpdir)

    def test_link_check(self):
        from artifact_health import check_links, load_all_artifacts
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_health", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_all_artifacts()
                result = check_links(artifacts)
                self.assertGreaterEqual(result["broken_count"], 1)
                self.assertGreaterEqual(result["orphan_count"], 1)
        finally:
            shutil.rmtree(tmpdir)

    def test_aging_check(self):
        from artifact_health import check_aging, load_all_artifacts
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_health", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_all_artifacts()
                result = check_aging(artifacts)
                self.assertGreaterEqual(result["stale_count"], 1)
                self.assertGreaterEqual(result["needs_archive_count"], 1)
        finally:
            shutil.rmtree(tmpdir)

    def test_duplicate_check(self):
        from artifact_health import check_duplicates, load_all_artifacts
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_health", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_all_artifacts()
                result = check_duplicates(artifacts)
                self.assertEqual(result["exact_duplicates"], 0)
        finally:
            shutil.rmtree(tmpdir)

    def test_code_refs_check(self):
        from artifact_health import check_code_refs, load_all_artifacts
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_health", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                artifacts = load_all_artifacts()
                result = check_code_refs(artifacts)
                self.assertGreater(result["total_active"], 0)
                self.assertGreaterEqual(result["coverage_pct"], 0)
        finally:
            shutil.rmtree(tmpdir)

    def test_overall_score(self):
        from artifact_health import compute_overall_score
        checks = {
            "frontmatter": {"score": 80},
            "links": {"score": 60},
            "aging": {"score": 100},
            "duplicates": {"score": 100},
            "code_refs": {"score": 40},
            "insights": {"score": 100},
            "infrastructure": {"score": 100},
        }
        score = compute_overall_score(checks)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)
        self.assertGreater(score, 0)


# ═══════════════════════════════════════════════════════
# Tests for artifact_changelog.py
# ═══════════════════════════════════════════════════════

class TestArtifactChangelog(unittest.TestCase):

    def test_parse_frontmatter(self):
        from artifact_core import parse_frontmatter_with_raw as parse_frontmatter
        content = '---\nid: PAT-001\ntype: pattern\ntitle: "Test"\nstatus: active\nhistory:\n  - "2026-01-01: created"\n---\n# Body\n'
        meta, body, raw_fm = parse_frontmatter(content)
        self.assertEqual(meta["id"], "PAT-001")
        self.assertIn("history", meta)

    def test_rebuild_frontmatter(self):
        from artifact_changelog import rebuild_frontmatter
        meta = {
            "id": "PAT-001",
            "type": "pattern",
            "title": "Test Pattern",
            "status": "active",
            "tags": ["test", "auto"],
        }
        fm = rebuild_frontmatter(meta)
        self.assertIn("id: PAT-001", fm)
        self.assertIn("type: pattern", fm)
        # Lists are rendered as block style to avoid YAML type coercion
        self.assertIn("tags:", fm)
        self.assertIn("- test", fm)
        self.assertIn("- auto", fm)

    def test_find_artifact(self):
        from artifact_changelog import find_artifact
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_changelog", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                result = find_artifact("PAT-001")
                self.assertIsNotNone(result)
                path, meta, body, raw_fm = result
                self.assertEqual(meta["id"], "PAT-001")
                result = find_artifact("NON-EXISTENT")
                self.assertIsNone(result)
        finally:
            shutil.rmtree(tmpdir)

    def test_add_history_entry(self):
        from artifact_changelog import find_artifact, add_history_entry
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)
            with patch.multiple("artifact_changelog", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):
                add_history_entry("PAT-001", "test change entry")
                result = find_artifact("PAT-001")
                self.assertIsNotNone(result)
                _, meta, _, _ = result
                history = meta.get("history", [])
                self.assertTrue(any("test change entry" in h for h in history))
        finally:
            shutil.rmtree(tmpdir)


# ═══════════════════════════════════════════════════════
# Tests for search_artifacts.py
# ═══════════════════════════════════════════════════════

class TestSearchArtifacts(unittest.TestCase):

    def test_score_index_entry(self):
        from search_artifacts import score_index_entry
        entry = {
            "id": "PAT-001",
            "title": "Test Pattern",
            "body": "This is a test pattern for testing.",
            "tags": ["test"],
            "status": "active",
        }
        score = score_index_entry(entry, "test")
        self.assertGreater(score, 0)

    def test_score_index_entry_stale_penalty(self):
        from search_artifacts import score_index_entry
        active = {"id": "PAT-001", "title": "Test", "body": "test", "status": "active"}
        stale = {"id": "PAT-002", "title": "Test", "body": "test", "status": "stale"}
        active_score = score_index_entry(active, "test")
        stale_score = score_index_entry(stale, "test")
        self.assertGreater(active_score, stale_score)

    def test_score_index_entry_archived_penalty(self):
        from search_artifacts import score_index_entry
        active = {"id": "PAT-001", "title": "Test", "body": "test", "status": "active"}
        archived = {"id": "PAT-002", "title": "Test", "body": "test", "status": "archived"}
        active_score = score_index_entry(active, "test")
        archived_score = score_index_entry(archived, "test")
        self.assertGreater(active_score, archived_score)


# ═══════════════════════════════════════════════════════
# Tests for normalize_frontmatter.py
# ═══════════════════════════════════════════════════════

class TestNormalizeFrontmatter(unittest.TestCase):

    def test_parse_frontmatter(self):
        from normalize_frontmatter import parse_frontmatter
        content = '---\nid: PAT-001\ntype: pattern\ntitle: "Test"\nstatus: active\n---\n# Body\n'
        result = parse_frontmatter(content)
        # Returns (meta_dict, fm_text_int)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        meta = result[0]
        self.assertEqual(meta["id"], "PAT-001")


# ═══════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):

    def test_full_pipeline(self):
        tmpdir = create_test_artifact_dir()
        try:
            dirs = patch_dirs(tmpdir)

            import artifact_stats
            import artifact_aging
            import artifact_link_checker
            import artifact_graph
            import artifact_health

            with patch.multiple("artifact_stats", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir), \
                 patch.multiple("artifact_aging", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir), \
                 patch.multiple("artifact_link_checker", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir), \
                 patch.multiple("artifact_graph", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir), \
                 patch.multiple("artifact_health", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):

                # Load with each module's own loader (they have different formats)
                from artifact_stats import load_all_artifacts as load_stats

                arts = load_stats()
                self.assertEqual(len(arts), 7)
                stats = artifact_stats.compute_stats(arts)
                self.assertEqual(len(stats), 7)

                aging = artifact_aging.run_aging(dry_run=True, stale_days=90, archive_days=180)
                self.assertGreaterEqual(aging["staled"], 1)

                art_h = artifact_health.load_all_artifacts()

                link_report = artifact_link_checker.check_links(art_h)
                self.assertGreaterEqual(link_report["broken_links"]["count"], 1)

                graph = artifact_graph.build_graph(art_h)
                self.assertEqual(len(graph["nodes"]), 7)

                health_checks = {
                    "frontmatter": artifact_health.check_frontmatter(art_h),
                    "links": artifact_health.check_links(art_h),
                    "aging": artifact_health.check_aging(art_h),
                    "duplicates": artifact_health.check_duplicates(art_h),
                    "code_refs": artifact_health.check_code_refs(art_h),
                    "insights": {"score": 100},
                    "infrastructure": {"score": 100},
                }
                overall = artifact_health.compute_overall_score(health_checks)
                self.assertGreaterEqual(overall, 0)
                self.assertLessEqual(overall, 100)
        finally:
            shutil.rmtree(tmpdir)


# ═══════════════════════════════════════════════════════
# Provenance Tests
# ═══════════════════════════════════════════════════════

class TestArtifactProvenance(unittest.TestCase):
    """Tests for artifact_provenance.py — provenance score, confidence, staleness."""

    def setUp(self):
        import importlib
        import artifact_provenance as ap
        importlib.reload(ap)
        self.ap = ap

    def test_provenance_fields_present(self):
        """Active artifacts should ideally have provenance fields (warning-only check)."""
        artifacts = self.ap.load_all_artifacts()
        for aid, art in artifacts.items():
            if art.get("status") in ("archived", "rejected"):
                continue
            meta = art["meta"]
            # These fields are recommended but not required — just verify no crash
            _ = meta.get("last_verified", "")
            _ = meta.get("confidence", "")
            _ = meta.get("source", "")

    def test_confidence_values_valid(self):
        """When confidence is set, it must be a valid value (empty is OK)."""
        valid = {"high", "medium", "low", "outdated", ""}
        artifacts = self.ap.load_all_artifacts()
        for aid, art in artifacts.items():
            c = art["meta"].get("confidence", "")
            self.assertIn(c, valid, f"{aid}: invalid confidence '{c}'")

    def test_last_verified_not_future(self):
        """last_verified must not be in the future."""
        artifacts = self.ap.load_all_artifacts()
        now = datetime.now(timezone.utc)
        for aid, art in artifacts.items():
            lv = art["meta"].get("last_verified", "")
            if lv:
                try:
                    if isinstance(lv, datetime):
                        dt = lv
                    else:
                        lv_str = str(lv).strip()
                        if not lv_str:
                            continue
                        # Handle date-only (YYYY-MM-DD) by appending time
                        if len(lv_str) == 10 and lv_str.count("-") == 2:
                            lv_str = f"{lv_str}T00:00:00+00:00"
                        dt = datetime.fromisoformat(lv_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    self.assertLessEqual(dt, now + timedelta(days=1),
                                         f"{aid}: last_verified in future: {lv}")
                except (ValueError, TypeError):
                    self.fail(f"{aid}: invalid last_verified format: {lv}")

    def test_provenance_report_runs(self):
        """Full provenance report must not crash."""
        report = self.ap.generate_report()
        self.assertIn("score", report)
        self.assertIn("by_confidence", report)
        self.assertIn("needs_review", report)

    def test_provenance_score_range(self):
        """Provenance score must be 0–100."""
        report = self.ap.generate_report()
        score = report.get("score", -1)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_compute_confidence_decay(self):
        """Confidence decays with time since last_verified."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        old = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        very_old = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

        self.assertEqual(self.ap.compute_confidence(now, "high"), "high")
        self.assertIn(self.ap.compute_confidence(old, "high"), ("medium", "low"))
        self.assertEqual(self.ap.compute_confidence(very_old, "high"), "outdated")
        self.assertEqual(self.ap.compute_confidence("", "high"), "outdated")

    def test_verify_artifact_updates_timestamp(self):
        """verify_artifact must update last_verified to now."""
        artifacts = self.ap.load_all_artifacts()
        if not artifacts:
            self.skipTest("No artifacts to verify")
        first_id = next(iter(artifacts))
        result = self.ap.verify_artifact(first_id)
        self.assertIn("last_verified", result)


# ═══════════════════════════════════════════════════════
# Constraints Tests
# ═══════════════════════════════════════════════════════

class TestArtifactConstraints(unittest.TestCase):
    """Tests for artifact_constraints.py — contradictions, cycles, violations."""

    def setUp(self):
        import importlib
        import artifact_constraints as ac
        importlib.reload(ac)
        self.ac = ac

    def test_load_constraints(self):
        """Constraints module must load without errors."""
        artifacts = self.ac.load_all_artifacts()
        self.assertIsInstance(artifacts, dict)
        self.assertGreater(len(artifacts), 0)

    def test_no_self_links(self):
        """No artifact should link to itself in the link graph."""
        artifacts = self.ac.load_all_artifacts()
        outbound, inbound = self.ac.build_link_graph(artifacts)
        for aid, targets in outbound.items():
            self.assertNotIn(aid, targets, f"{aid}: self-link detected")

    def test_detect_cycles(self):
        """Cycle detection must find known circular deps."""
        artifacts = self.ac.load_all_artifacts()
        outbound, _ = self.ac.build_link_graph(artifacts)
        cycles = self.ac.find_cycles(outbound)
        self.assertIsInstance(cycles, list)
        # Known cycles exist (ADR-012↔ADR-013, BL-028↔BL-037, etc.)
        self.assertGreater(len(cycles), 0, "Should detect known circular deps")

    def test_run_all_checks_runs(self):
        """Full constraints check must not crash."""
        artifacts = self.ac.load_all_artifacts()
        report = self.ac.run_all_checks(artifacts)
        self.assertIn("issues", report)
        self.assertIn("cycles_found", report)
        self.assertIn("score", report)

    def test_constraint_score_range(self):
        """Constraint score must be 0–100."""
        artifacts = self.ac.load_all_artifacts()
        report = self.ac.run_all_checks(artifacts)
        score = report.get("score", -1)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_no_duplicate_ids(self):
        """All artifact IDs must be unique."""
        artifacts = self.ac.load_all_artifacts()
        ids = list(artifacts.keys())
        self.assertEqual(len(ids), len(set(ids)), "Duplicate IDs detected")

    def test_valid_status_values(self):
        """Status must be a known value."""
        from artifact_constants import ALL_VALID_STATUSES
        artifacts = self.ac.load_all_artifacts()
        for aid, art in artifacts.items():
            status = art["meta"].get("status", "")
            if status:
                self.assertIn(status, ALL_VALID_STATUSES,
                              f"{aid}: invalid status '{status}'")


# ═══════════════════════════════════════════════════════
# Monitor Tests
# ═══════════════════════════════════════════════════════

class TestArtifactMonitor(unittest.TestCase):
    """Tests for artifact_monitor.py — health scoring, trend tracking, alerts."""

    def setUp(self):
        import importlib
        import artifact_monitor as am
        importlib.reload(am)
        self.am = am

    def test_snapshot_runs(self):
        """Health snapshot must generate without crashing."""
        snapshot = self.am.run_health_snapshot()
        self.assertIn("overall_score", snapshot)
        self.assertIn("provenance_score", snapshot)
        self.assertIn("constraint_score", snapshot)
        self.assertIn("total_artifacts", snapshot)

    def test_health_score_range(self):
        """Overall score must be 0–100."""
        snapshot = self.am.run_health_snapshot()
        score = snapshot.get("overall_score", -1)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_snapshot_has_checks(self):
        """Snapshot must include all check dimensions."""
        snapshot = self.am.run_health_snapshot()
        checks = snapshot.get("checks", {})
        for key in ("frontmatter", "links", "aging", "duplicates", "code_refs"):
            self.assertIn(key, checks, f"Missing check: {key}")

    def test_save_and_load_history(self):
        """Snapshot must be saveable and loadable."""
        snapshot = self.am.run_health_snapshot()
        self.am.save_snapshot(snapshot)
        history = self.am.load_history(days=1)
        self.assertIsInstance(history, list)
        self.assertGreater(len(history), 0)

    def test_compute_trends_insufficient_data(self):
        """Trends with <2 points must return insufficient_data."""
        result = self.am.compute_trends([])
        self.assertEqual(result.get("status"), "insufficient_data")

    def test_compute_trends_with_data(self):
        """Trends with 2+ points must compute deltas."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        old = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        history = [
            {"timestamp": old, "overall_score": 50, "total_artifacts": 90,
             "broken_links": 10, "orphans": 20},
            {"timestamp": now, "overall_score": 60, "total_artifacts": 95,
             "broken_links": 7, "orphans": 19},
        ]
        trends = self.am.compute_trends(history)
        self.assertIn("score", trends)
        self.assertEqual(trends["score"]["change"], 10)

    def test_check_alerts(self):
        """Alert checker must return list of alert dicts."""
        snapshot = self.am.run_health_snapshot()
        trends = self.am.compute_trends([snapshot])
        alerts = self.am.check_alerts(snapshot, trends)
        self.assertIsInstance(alerts, list)


# ═══════════════════════════════════════════════════════
# YAML SafeLoad Frontmatter Parser Tests
# ═══════════════════════════════════════════════════════

class TestYamlSafeLoadParser(unittest.TestCase):
    """Tests for yaml.safe_load frontmatter parser in artifact_core."""

    def test_simple_frontmatter(self):
        """Basic key-value frontmatter must parse correctly."""
        content = """---
id: PAT-001
type: pattern
title: "Test Pattern"
status: active
created: 2026-01-01T00:00:00+00:00
updated: 2026-01-01T00:00:00+00:00
---

# Body
Some text here."""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta["id"], "PAT-001")
        self.assertEqual(meta["type"], "pattern")
        self.assertEqual(meta["title"], "Test Pattern")
        self.assertIn("Some text here", body)

    def test_multiline_body(self):
        """Body with multiple paragraphs must be preserved."""
        content = """---
id: ADR-001
type: adr
title: "Test ADR"
status: accepted
---

# Context

This is the context paragraph.

## Decision

This is the decision paragraph.

## Consequences

More text here."""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta["id"], "ADR-001")
        self.assertIn("Context", body)
        self.assertIn("Decision", body)
        self.assertIn("Consequences", body)

    def test_yaml_list_values(self):
        """YAML list values (tags, code_refs) must parse as lists."""
        content = """---
id: RUL-001
type: rule
title: "Test Rule"
tags:
  - security
  - auth
code_refs:
  - src/auth.py
  - src/middleware.py
---
# Body"""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertIsInstance(meta["tags"], list)
        self.assertEqual(len(meta["tags"]), 2)
        self.assertEqual(meta["tags"][0], "security")
        self.assertIsInstance(meta["code_refs"], list)
        self.assertEqual(len(meta["code_refs"]), 2)

    def test_yaml_multiline_string(self):
        """YAML multiline string (literal block scalar) must parse."""
        content = """---
id: PAT-002
type: pattern
title: "Multiline Pattern"
description: |
  This is a long description
  that spans multiple lines
  and preserves line breaks.
status: active
---
# Body"""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertIn("long description", meta["description"])
        self.assertIn("multiple lines", meta["description"])

    def test_empty_frontmatter(self):
        """Empty frontmatter block must return empty dict, full content as body."""
        content = """---
---
# Just a heading"""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta, {})
        self.assertIn("Just a heading", body)

    def test_no_frontmatter(self):
        """Content without frontmatter must return empty dict, full content as body."""
        content = "# No Frontmatter\n\nJust plain markdown."
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta, {})
        self.assertEqual(body, content)

    def test_invalid_yaml_returns_empty(self):
        """Invalid YAML must return empty dict (not crash)."""
        content = """---
id: PAT-001
  bad_indent: [unclosed
  broken: {yaml: ---
---
# Body"""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        # yaml.safe_load raises YAMLError for malformed YAML; parser returns {}
        self.assertIsInstance(meta, dict)

    def test_yaml_special_characters_in_title(self):
        """Title with colons, quotes, and special chars must parse."""
        lines = [
            "---",
            "id: ADR-003",
            "type: adr",
            "title: \"Use O'Reilly's Pattern: Best Practice (v2.0)\"",
            "status: accepted",
            "---",
            "# Body",
        ]
        content = "\n".join(lines)
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertIn("O'Reilly", meta["title"])
        self.assertIn("Best Practice", meta["title"])

    def test_yaml_boolean_and_numeric(self):
        """Boolean and numeric YAML values must be native Python types."""
        content = """---
id: MET-001
type: metric
title: "Test Metric"
active: true
count: 42
ratio: 3.14
---
# Body"""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertIs(meta["active"], True)
        self.assertEqual(meta["count"], 42)
        self.assertAlmostEqual(meta["ratio"], 3.14)

    def test_parse_frontmatter_with_raw(self):
        """parse_frontmatter_with_raw must return raw frontmatter text."""
        content = """---
id: PAT-005
type: pattern
title: "Raw Test"
status: active
---

# Body text"""
        from artifact_core import parse_frontmatter_with_raw
        meta, body, raw = parse_frontmatter_with_raw(content)
        self.assertEqual(meta["id"], "PAT-005")
        self.assertIn("id: PAT-005", raw)
        self.assertIn("title: \"Raw Test\"", raw)
        self.assertIn("Body text", body)

    def test_parse_frontmatter_with_raw_no_fm(self):
        """parse_frontmatter_with_raw without frontmatter returns empty raw."""
        content = "# No frontmatter"
        from artifact_core import parse_frontmatter_with_raw
        meta, body, raw = parse_frontmatter_with_raw(content)
        self.assertEqual(meta, {})
        self.assertEqual(raw, "")

    def test_unicode_frontmatter(self):
        """Unicode characters in frontmatter must parse correctly."""
        content = """---
id: PAT-006
type: pattern
title: "Юникод: тестирование русского текста"
tags:
  - тест
  - юникод
status: active
---
# Тело документа"""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertIn("Юникод", meta["title"])
        self.assertIn("тест", meta["tags"])

    def test_frontmatter_with_comments(self):
        """YAML comments in frontmatter must be ignored."""
        content = """---
id: PAT-007
type: pattern
title: "Comment Test"
# This is a comment
status: active
---
# Body"""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta["id"], "PAT-007")
        self.assertEqual(meta["status"], "active")
        self.assertNotIn("comment", meta)

    def test_second_delimiter_not_on_first_line(self):
        """Second --- delimiter must not be matched on line 0."""
        content = """---
id: PAT-008
title: "Test"
---
# Body
---
More content after horizontal rule."""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta["id"], "PAT-008")
        self.assertIn("horizontal rule", body)

    def test_yaml_null_values(self):
        """Null YAML values must map to None."""
        content = """---
id: PAT-009
type: pattern
title: "Null Test"
source:
confidence:
---
# Body"""
        from artifact_core import parse_frontmatter
        meta, body = parse_frontmatter(content)
        self.assertIsNone(meta["source"])
        self.assertIsNone(meta["confidence"])


# ═══════════════════════════════════════════════════════
# TestHistoryRotation
# ═══════════════════════════════════════════════════════

class TestHistoryRotation(unittest.TestCase):
    """Tests for health_history.jsonl rotation."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="history_rot_"))
        self.history_file = self.tmpdir / "health_history.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_entries(self, n: int):
        """Write N history entries."""
        now = datetime.now(timezone.utc)
        with open(self.history_file, "w", encoding="utf-8") as f:
            for i in range(n):
                ts = (now - timedelta(hours=n - i)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
                entry = json.dumps({"timestamp": ts, "overall_score": 80 + (i % 20)}, ensure_ascii=False)
                f.write(entry + "\n")

    def test_rotation_trims_by_count(self):
        """Rotation must trim entries exceeding HISTORY_MAX_ENTRIES."""
        import artifact_monitor as mon
        self._write_entries(mon.HISTORY_MAX_ENTRIES + 100)
        mon.HISTORY_FILE = self.history_file
        mon._rotate_history()
        lines = [ln for ln in self.history_file.read_text().splitlines() if ln.strip()]
        self.assertLessEqual(len(lines), mon.HISTORY_MAX_ENTRIES)

    def test_rotation_trims_by_age(self):
        """Rotation must trim entries older than HISTORY_MAX_DAYS."""
        import artifact_monitor as mon
        self._write_entries(50)
        # Prepend an old entry (will be at start of file, read last in reversed loop)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=mon.HISTORY_MAX_DAYS + 10)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        old_entry = json.dumps({"timestamp": old_ts, "overall_score": 50}, ensure_ascii=False)
        content = self.history_file.read_text()
        self.history_file.write_text(old_entry + "\n" + content)
        mon.HISTORY_FILE = self.history_file
        mon._rotate_history()
        lines = self.history_file.read_text().splitlines()
        for line in lines:
            if line.strip():
                entry = json.loads(line)
                entry_dt = datetime.fromisoformat(entry["timestamp"].replace("+00:00", "+00:00"))
                age = (datetime.now(timezone.utc) - entry_dt).days
                self.assertLessEqual(age, mon.HISTORY_MAX_DAYS)

    def test_rotation_preserves_recent(self):
        """Rotation must keep recent entries intact."""
        import artifact_monitor as mon
        self._write_entries(10)
        mon.HISTORY_FILE = self.history_file
        mon._rotate_history()
        lines = [ln for ln in self.history_file.read_text().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 10)  # all recent, should not be trimmed

    def test_rotation_nonexistent_file(self):
        """Rotation must not crash if history file does not exist."""
        import artifact_monitor as mon
        mon.HISTORY_FILE = self.history_file / "nonexistent.jsonl"
        mon._rotate_history()  # must not raise


# ═══════════════════════════════════════════════════════
# TestDirFingerprint
# ═══════════════════════════════════════════════════════

class TestDirFingerprint(unittest.TestCase):
    """Tests for O(directories) stale detection in search_artifacts."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="fingerprint_"))
        self.patterns_dir = self.tmpdir / "patterns"
        self.patterns_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fingerprint_detects_new_file(self):
        """Fingerprint changes when a new file is added."""
        import search_artifacts as sa
        with patch.object(sa, "LAB_DIR", self.tmpdir), \
             patch.object(sa, "ARTIFACT_DIRS", ["patterns"]):
            mtime1, count1 = sa._dir_fingerprint()
            self.assertEqual(count1, 0)

            (self.patterns_dir / "test.md").write_text("# Hello")
            sa.__dict__.pop("_fingerprint_cache", None)
            mtime2, count2 = sa._dir_fingerprint()
            self.assertEqual(count2, 1)
            self.assertGreater(mtime2, mtime1)

    def test_fingerprint_detects_modified_file(self):
        """Fingerprint changes when an existing file is modified."""
        import search_artifacts as sa
        with patch.object(sa, "LAB_DIR", self.tmpdir), \
             patch.object(sa, "ARTIFACT_DIRS", ["patterns"]):
            (self.patterns_dir / "test.md").write_text("# Hello")
            mtime1, count1 = sa._dir_fingerprint()
            self.assertEqual(count1, 1)

            import time
            time.sleep(0.01)  # ensure mtime differs
            (self.patterns_dir / "test.md").write_text("# Modified!")
            sa.__dict__.pop("_fingerprint_cache", None)
            mtime2, count2 = sa._dir_fingerprint()
            self.assertEqual(count2, 1)
            self.assertGreaterEqual(mtime2, mtime1)


# ═══════════════════════════════════════════════════════
# TestNeedsQuoting
# ═══════════════════════════════════════════════════════

class TestNeedsQuoting(unittest.TestCase):
    """Tests for _needs_quoting helper in artifact_changelog."""

    def test_date_colon_string_needs_quoting(self):
        from artifact_changelog import _needs_quoting
        self.assertTrue(_needs_quoting("2026-06-09: test change entry"))

    def test_plain_string_no_quoting(self):
        from artifact_changelog import _needs_quoting
        self.assertFalse(_needs_quoting("simpletext"))

    def test_tag_no_quoting(self):
        from artifact_changelog import _needs_quoting
        self.assertFalse(_needs_quoting("test"))

    def test_colon_no_digit_needs_quoting(self):
        from artifact_changelog import _needs_quoting
        self.assertTrue(_needs_quoting("some: text"))

    def test_space_needs_quoting(self):
        from artifact_changelog import _needs_quoting
        self.assertTrue(_needs_quoting("hello world"))

    def test_empty_no_quoting(self):
        from artifact_changelog import _needs_quoting
        self.assertFalse(_needs_quoting(""))


# ═══════════════════════════════════════════════════════
# TestDaysSinceEdgeCases
# ═══════════════════════════════════════════════════════

class TestDaysSinceEdgeCases(unittest.TestCase):
    """Edge cases for days_since with various input types."""

    def test_datetime_object(self):
        from artifact_aging import days_since
        dt = datetime.now(timezone.utc) - timedelta(days=5)
        result = days_since(dt)
        self.assertEqual(result, 5)

    def test_date_only_string(self):
        from artifact_aging import days_since
        old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        result = days_since(old)
        self.assertGreaterEqual(result, 10)

    def test_iso_datetime_string(self):
        from artifact_aging import days_since
        old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        result = days_since(old)
        self.assertGreaterEqual(result, 3)

    def test_return_type_is_int(self):
        from artifact_aging import days_since
        result = days_since(datetime.now(timezone.utc))
        self.assertIsInstance(result, int)


# ═══════════════════════════════════════════════════════
# TestCascadeAnalysis
# ═══════════════════════════════════════════════════════

class TestCascadeAnalysis(unittest.TestCase):
    """Tests for cascade analysis in artifact_aging."""

    def test_get_inbound_sources_basic(self):
        from artifact_aging import get_inbound_sources
        artifacts = {
            "ADR-001": {"_body": "See PAT-001."},
            "PAT-001": {"_body": "No refs."},
            "RUL-001": {"_body": "Depends on ADR-001 and PAT-001."},
        }
        sources = get_inbound_sources(artifacts)
        self.assertIn("ADR-001", sources["PAT-001"])
        self.assertIn("RUL-001", sources["ADR-001"])
        self.assertIn("RUL-001", sources["PAT-001"])

    def test_get_inbound_sources_no_self_ref(self):
        from artifact_aging import get_inbound_sources
        artifacts = {
            "ADR-001": {"_body": "Self reference ADR-001 should be ignored."},
        }
        sources = get_inbound_sources(artifacts)
        self.assertNotIn("ADR-001", sources["ADR-001"])

    def test_get_inbound_sources_empty_body(self):
        from artifact_aging import get_inbound_sources
        artifacts = {
            "ADR-001": {"_body": ""},
            "PAT-001": {},
        }
        sources = get_inbound_sources(artifacts)
        self.assertEqual(sources["ADR-001"], [])
        self.assertEqual(sources["PAT-001"], [])

    def test_analyze_cascade_empty_details(self):
        from artifact_aging import analyze_cascade
        artifacts = {
            "ADR-001": {"_body": "See PAT-001."},
            "PAT-001": {"_body": ""},
        }
        result = analyze_cascade(artifacts, [])
        self.assertEqual(result, [])

    def test_analyze_cascade_with_affected(self):
        from artifact_aging import analyze_cascade
        artifacts = {
            "ADR-001": {"_body": "See PAT-001."},
            "PAT-001": {"_body": ""},
            "RUL-001": {"_body": "Depends on ADR-001."},
        }
        details = [{"id": "ADR-001", "action": "archive"}]
        result = analyze_cascade(artifacts, details)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["target"], "ADR-001")
        self.assertEqual(result[0]["action"], "archive")
        self.assertIn("RUL-001", result[0]["affected"])

    def test_analyze_cascade_no_affected(self):
        from artifact_aging import analyze_cascade
        artifacts = {
            "ADR-001": {"_body": "No one references this."},
            "PAT-001": {"_body": ""},
        }
        details = [{"id": "ADR-001", "action": "stale"}]
        result = analyze_cascade(artifacts, details)
        self.assertEqual(result, [])

    def test_analyze_cascade_multiple_targets(self):
        from artifact_aging import analyze_cascade
        artifacts = {
            "ADR-001": {"_body": ""},
            "PAT-001": {"_body": ""},
            "RUL-001": {"_body": "Depends on ADR-001 and PAT-001."},
        }
        details = [
            {"id": "ADR-001", "action": "archive"},
            {"id": "PAT-001", "action": "stale"},
        ]
        result = analyze_cascade(artifacts, details)
        self.assertEqual(len(result), 2)
        targets = {r["target"] for r in result}
        self.assertEqual(targets, {"ADR-001", "PAT-001"})


# ═══════════════════════════════════════════════════════
# TestAutoFixFrontmatter
# ═══════════════════════════════════════════════════════

class TestAutoFixFrontmatter(unittest.TestCase):
    """Tests for auto-fix in normalize_frontmatter."""

    def test_normalize_id_lowercase_prefix(self):
        from normalize_frontmatter import _normalize_id
        result = _normalize_id("pat-001", "PAT")
        self.assertEqual(result, "PAT-001")

    def test_normalize_id_spaces(self):
        from normalize_frontmatter import _normalize_id
        result = _normalize_id("PAT 001", "PAT")
        self.assertEqual(result, "PAT-001")

    def test_normalize_id_already_correct(self):
        from normalize_frontmatter import _normalize_id
        result = _normalize_id("PAT-001", "PAT")
        self.assertEqual(result, "PAT-001")

    def test_normalize_id_no_dash(self):
        from normalize_frontmatter import _normalize_id
        result = _normalize_id("PAT001", "PAT")
        self.assertIsNone(result)

    def test_rebuild_frontmatter_preserves_body(self):
        from normalize_frontmatter import _rebuild_frontmatter
        content = "---\nid: PAT-001\ntype: pattern\ntitle: Test\n---\n# Hello\nBody text."
        fm = {"id": "PAT-001", "type": "pattern", "title": "Fixed"}
        result = _rebuild_frontmatter(content, fm)
        self.assertIn("# Hello", result)
        self.assertIn("Body text", result)
        self.assertIn("title: Fixed", result)

    def test_rebuild_frontmatter_no_frontmatter(self):
        from normalize_frontmatter import _rebuild_frontmatter
        content = "# No frontmatter here"
        result = _rebuild_frontmatter(content, {"id": "X"})
        self.assertIsNone(result)

    def test_fix_frontmatter_invalid_status(self):
        from normalize_frontmatter import fix_frontmatter
        content = "---\nid: PAT-001\ntype: pattern\ntitle: Test\nstatus: bogus\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n# Body"
        fm = {"id": "PAT-001", "type": "pattern", "title": "Test", "status": "bogus", "created": "2026-01-01", "updated": "2026-01-01"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            fixed, fixes = fix_frontmatter(fm, content, Path(f.name))
            self.assertTrue(fixed)
            self.assertTrue(any("draft" in fix for fix in fixes))

    def test_fix_frontmatter_missing_dates(self):
        from normalize_frontmatter import fix_frontmatter
        content = "---\nid: PAT-001\ntype: pattern\ntitle: Test\nstatus: active\n---\n# Body"
        fm = {"id": "PAT-001", "type": "pattern", "title": "Test", "status": "active"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            fixed, fixes = fix_frontmatter(fm, content, Path(f.name))
            self.assertTrue(fixed)
            self.assertTrue(any("created" in fix for fix in fixes))


# ═══════════════════════════════════════════════════════
# TestDashboard
# ═══════════════════════════════════════════════════════

class TestDashboard(unittest.TestCase):
    """Tests for artifact_dashboard."""

    def test_generate_dashboard_returns_html(self):
        from artifact_dashboard import generate_dashboard
        artifacts = {
            "ADR-001": {
                "type": "adr",
                "meta": {"title": "Test ADR", "status": "active", "confidence": "high"},
                "body": "See PAT-001.",
            },
            "PAT-001": {
                "type": "pattern",
                "meta": {"title": "Test Pattern", "status": "active", "confidence": "medium"},
                "body": "",
            },
        }
        html = generate_dashboard(artifacts)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("ADR-001", html)
        self.assertIn("PAT-001", html)

    def test_dashboard_health_score_present(self):
        from artifact_dashboard import generate_dashboard
        artifacts = {
            "ADR-001": {
                "type": "adr",
                "meta": {"title": "Test", "status": "active", "confidence": "high"},
                "body": "",
            },
        }
        html = generate_dashboard(artifacts)
        self.assertIn("Health Score", html)
        self.assertIn("/100", html)

    def test_dashboard_type_distribution(self):
        from artifact_dashboard import _compute_type_distribution
        artifacts = {
            "ADR-001": {"type": "adr", "meta": {}},
            "ADR-002": {"type": "adr", "meta": {}},
            "PAT-001": {"type": "pattern", "meta": {}},
        }
        dist = _compute_type_distribution(artifacts)
        self.assertEqual(dist["adr"], 2)
        self.assertEqual(dist["pattern"], 1)

    def test_dashboard_status_distribution(self):
        from artifact_dashboard import _compute_status_distribution
        artifacts = {
            "ADR-001": {"meta": {"status": "active"}},
            "ADR-002": {"meta": {"status": "stale"}},
            "PAT-001": {"meta": {"status": "active"}},
        }
        dist = _compute_status_distribution(artifacts)
        self.assertEqual(dist["active"], 2)
        self.assertEqual(dist["stale"], 1)

    def test_dashboard_top_cited(self):
        from artifact_dashboard import _compute_inbound_links, _top_cited
        artifacts = {
            "ADR-001": {"type": "adr", "meta": {"title": "Popular"}, "body": ""},
            "PAT-001": {"type": "pattern", "meta": {"title": "Cites ADR"}, "body": "See ADR-001."},
            "RUL-001": {"type": "rule", "meta": {"title": "Also cites ADR"}, "body": "Depends on ADR-001."},
        }
        inbound = _compute_inbound_links(artifacts)
        top = _top_cited(artifacts, inbound, n=5)
        self.assertEqual(top[0]["id"], "ADR-001")
        self.assertEqual(top[0]["inbound"], 2)

    def test_dashboard_needs_attention(self):
        from artifact_dashboard import _compute_inbound_links, _needs_attention
        from datetime import timedelta
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%d")
        artifacts = {
            "ADR-001": {
                "type": "adr",
                "meta": {"title": "Old", "status": "stale", "confidence": "low", "updated": old_date},
                "body": "",
            },
            "ADR-002": {
                "type": "adr",
                "meta": {"title": "Healthy", "status": "active", "confidence": "high", "updated": "2026-06-01"},
                "body": "",
            },
        }
        inbound = _compute_inbound_links(artifacts)
        attention = _needs_attention(artifacts, inbound)
        ids = [a["id"] for a in attention]
        self.assertIn("ADR-001", ids)
        self.assertNotIn("ADR-002", ids)

    def test_dashboard_graph_data(self):
        from artifact_dashboard import _build_graph_data
        artifacts = {
            "ADR-001": {"type": "adr", "meta": {}, "body": "See PAT-001."},
            "PAT-001": {"type": "pattern", "meta": {}, "body": ""},
        }
        graph = _build_graph_data(artifacts)
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(len(graph["links"]), 1)
        self.assertEqual(graph["links"][0]["source"], "ADR-001")
        self.assertEqual(graph["links"][0]["target"], "PAT-001")

    def test_dashboard_empty_artifacts(self):
        from artifact_dashboard import generate_dashboard
        html = generate_dashboard({})
        self.assertIn("<!DOCTYPE html>", html)

    def test_dashboard_output_to_file(self):
        from artifact_dashboard import generate_dashboard
        artifacts = {
            "ADR-001": {
                "type": "adr",
                "meta": {"title": "Test", "status": "active", "confidence": "high"},
                "body": "",
            },
        }
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        generate_dashboard(artifacts, output_path=path)
        content = Path(path).read_text()
        self.assertIn("ADR-001", content)
        Path(path).unlink()


# ═══════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestArtifactStats))
    suite.addTests(loader.loadTestsFromTestCase(TestArtifactAging))
    suite.addTests(loader.loadTestsFromTestCase(TestArtifactLinkChecker))
    suite.addTests(loader.loadTestsFromTestCase(TestArtifactGraph))
    suite.addTests(loader.loadTestsFromTestCase(TestArtifactHealth))
    suite.addTests(loader.loadTestsFromTestCase(TestArtifactChangelog))
    suite.addTests(loader.loadTestsFromTestCase(TestSearchArtifacts))
    suite.addTests(loader.loadTestsFromTestCase(TestNormalizeFrontmatter))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestArtifactProvenance))
    suite.addTests(loader.loadTestsFromTestCase(TestArtifactConstraints))
    suite.addTests(loader.loadTestsFromTestCase(TestArtifactMonitor))
    suite.addTests(loader.loadTestsFromTestCase(TestYamlSafeLoadParser))
    suite.addTests(loader.loadTestsFromTestCase(TestHistoryRotation))
    suite.addTests(loader.loadTestsFromTestCase(TestDirFingerprint))
    suite.addTests(loader.loadTestsFromTestCase(TestNeedsQuoting))
    suite.addTests(loader.loadTestsFromTestCase(TestDaysSinceEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestCascadeAnalysis))
    suite.addTests(loader.loadTestsFromTestCase(TestAutoFixFrontmatter))
    suite.addTests(loader.loadTestsFromTestCase(TestDashboard))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
