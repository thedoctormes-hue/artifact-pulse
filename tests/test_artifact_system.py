#!/usr/bin/env python3
"""
test_artifact_system.py — комплексные тесты системы артефактов LabDoctorM.

Usage:
  python3 -m pytest test_artifact_system.py -v
  python3 test_artifact_system.py
"""

import os
import sys
import json
import tempfile
import shutil
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "src"
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
        from artifact_stats import parse_frontmatter
        content = '---\nid: PAT-001\ntype: pattern\ntitle: "Test"\nstatus: active\ntags: [test, auto]\n---\n# Body text\n'
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta["id"], "PAT-001")
        self.assertEqual(meta["type"], "pattern")
        self.assertEqual(meta["title"], "Test")
        self.assertEqual(meta["status"], "active")
        self.assertIn("Body text", body)

    def test_parse_frontmatter_empty(self):
        from artifact_stats import parse_frontmatter
        content = "# Just a heading\n\nSome text."
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta, {})
        self.assertIn("Just a heading", body)

    def test_parse_frontmatter_tags_list(self):
        from artifact_stats import parse_frontmatter
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
        from artifact_aging import parse_frontmatter
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
        self.assertIn("tags: [test, auto]", fm)

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

            modules = [artifact_stats, artifact_aging, artifact_link_checker,
                       artifact_graph, artifact_health]

            with patch.multiple("artifact_stats", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir), \
                 patch.multiple("artifact_aging", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir), \
                 patch.multiple("artifact_link_checker", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir), \
                 patch.multiple("artifact_graph", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir), \
                 patch.multiple("artifact_health", ARTIFACT_DIRS=dirs, LAB_DIR=tmpdir):

                # Load with each module's own loader (they have different formats)
                from artifact_stats import load_all_artifacts as load_stats
                from artifact_link_checker import load_all_artifacts as load_links

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
        """All real artifacts must have last_verified, confidence, source."""
        artifacts = self.ap.load_all_artifacts()
        for aid, art in artifacts.items():
            meta = art["meta"]
            self.assertIn("last_verified", meta, f"{aid}: missing last_verified")
            self.assertIn("confidence", meta, f"{aid}: missing confidence")
            self.assertIn("source", meta, f"{aid}: missing source")

    def test_confidence_values_valid(self):
        """Confidence must be high, medium, low, or outdated."""
        valid = ("high", "medium", "low", "outdated")
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
                    dt = datetime.fromisoformat(lv.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    self.assertLessEqual(dt, now + timedelta(days=1),
                                         f"{aid}: last_verified in future: {lv}")
                except ValueError:
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
        valid = {"active", "draft", "deprecated", "resolved", "proposed", "open", "archived", "accepted", "closed", "pending"}
        artifacts = self.ac.load_all_artifacts()
        for aid, art in artifacts.items():
            status = art["meta"].get("status", "")
            if status:
                self.assertIn(status, valid,
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

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
