from __future__ import annotations

import copy
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("current_renderer_audit", ROOT / "tools/check-current-renderer-audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class CurrentAuditTest(unittest.TestCase):
    def test_only_a_complete_zero_finding_report_can_admit_the_new_renderer(self):
        report = {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {"vulnerabilities": {
            name: 0 for name in ("info", "low", "moderate", "high", "critical", "total")}}}
        audit.check_report(report, 0)
        for patch in ({"error": "registry unavailable"}, {"auditReportVersion": 1}, {"vulnerabilities": {"dompurify": {"severity": "low"}}}, {"metadata": {}}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                audit.check_report({**copy.deepcopy(report), **patch}, 0)
        with self.assertRaises(ValueError):
            audit.check_report(report, 1)
