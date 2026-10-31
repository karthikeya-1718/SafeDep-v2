"""Unit tests for SafeDep risk ranker module."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safedep.call_graph import get_affected_call_sites
from safedep.risk_ranker import (
    format_risk_report,
    get_risk_level,
    get_risk_ranked_call_sites,
    rank_affected_call_sites,
    rank_by_risk,
    rank_risk,
)


class TestRiskRanker(unittest.TestCase):
    """Test suite for ranking affected call sites by risk."""

    def test_empty_call_sites(self):
        """Test ranking an empty list returns an empty list."""
        self.assertEqual(rank_affected_call_sites([]), [])

    def test_ranking_by_call_frequency(self):
        """Test that functions called more frequently receive higher risk scores at same depth."""
        call_sites = [
            # calculate_tax called 3 times
            {
                "file_path": "billing.py",
                "function_name": "calculate_tax",
                "callee_name": "calculate_tax",
                "line_number": 10,
                "caller_name": "process_order",
            },
            {
                "file_path": "billing.py",
                "function_name": "calculate_tax",
                "callee_name": "calculate_tax",
                "line_number": 20,
                "caller_name": "checkout",
            },
            {
                "file_path": "invoice.py",
                "function_name": "calculate_tax",
                "callee_name": "calculate_tax",
                "line_number": 30,
                "caller_name": "generate_invoice",
            },
            # disconnect called 1 time
            {
                "file_path": "client.py",
                "function_name": "disconnect",
                "callee_name": "disconnect",
                "line_number": 40,
                "caller_name": "shutdown",
            },
        ]

        ranked = rank_affected_call_sites(call_sites)
        self.assertEqual(len(ranked), 4)

        # First 3 items should be calculate_tax
        for item in ranked[:3]:
            self.assertEqual(item["callee_name"], "calculate_tax")
            self.assertEqual(item["call_count"], 3)
            self.assertGreater(item["risk_score"], ranked[-1]["risk_score"])

        # Last item should be disconnect
        self.assertEqual(ranked[-1]["callee_name"], "disconnect")
        self.assertEqual(ranked[-1]["call_count"], 1)

    def test_ranking_by_call_chain_depth(self):
        """Test that deeper call chain locations receive higher risk scores for equal call counts."""
        call_sites = [
            # Call site in shallow root function
            {
                "file_path": "app.py",
                "function_name": "shallow_func",
                "callee_name": "shallow_func",
                "line_number": 5,
                "caller_name": "<module>",
            },
            # Call site in nested chain: main -> service -> deep_func
            {
                "file_path": "app.py",
                "function_name": "deep_func",
                "callee_name": "deep_func",
                "line_number": 25,
                "caller_name": "OrderService.execute.deep_func",
            },
        ]

        ranked = rank_affected_call_sites(call_sites)
        self.assertEqual(len(ranked), 2)
        # Deep function must be ranked higher than shallow function
        self.assertEqual(ranked[0]["callee_name"], "deep_func")
        self.assertGreater(ranked[0]["depth"], ranked[1]["depth"])
        self.assertGreater(ranked[0]["risk_score"], ranked[1]["risk_score"])

    def test_combined_frequency_and_depth_formula(self):
        """Test risk_score = call_count * depth and sorting descending."""
        call_sites = [
            {
                "file_path": "a.py",
                "function_name": "fn_low",
                "callee_name": "fn_low",
                "line_number": 1,
                "caller_name": "root",
            },
            {
                "file_path": "b.py",
                "function_name": "fn_high",
                "callee_name": "fn_high",
                "line_number": 2,
                "caller_name": "root.sub.deep",
            },
            {
                "file_path": "c.py",
                "function_name": "fn_high",
                "callee_name": "fn_high",
                "line_number": 3,
                "caller_name": "root.sub.deep",
            },
        ]

        ranked = rank_affected_call_sites(call_sites)

        # Verify sorted from highest to lowest
        scores = [item["risk_score"] for item in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

        for item in ranked:
            self.assertEqual(item["risk_score"], item["call_count"] * item["depth"])
            self.assertIn("risk_explanation", item)
            self.assertIn("risk_level", item)

    def test_risk_level_categories(self):
        """Test risk level string assignment based on score thresholds."""
        self.assertEqual(get_risk_level(15.0), "CRITICAL")
        self.assertEqual(get_risk_level(10.0), "CRITICAL")
        self.assertEqual(get_risk_level(6.0), "HIGH")
        self.assertEqual(get_risk_level(5.0), "HIGH")
        self.assertEqual(get_risk_level(3.0), "MEDIUM")
        self.assertEqual(get_risk_level(2.0), "MEDIUM")
        self.assertEqual(get_risk_level(1.0), "LOW")

    def test_end_to_end_with_call_graph(self):
        """Test integration: get_affected_call_sites followed by rank_affected_call_sites."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            code_file = project_dir / "client.py"
            code_file.write_text(
                """
def top_call():
    calculate_tax(10)

def deep_chain():
    def inner():
        calculate_tax(20)
    inner()

def single_call():
    disconnect()
""",
                encoding="utf-8",
            )

            breaking = ["calculate_tax", "disconnect"]
            raw_sites = get_affected_call_sites(code_file, breaking)
            self.assertEqual(len(raw_sites), 3)

            ranked = rank_affected_call_sites(raw_sites, project_path=code_file)
            self.assertEqual(len(ranked), 3)

            # calculate_tax called twice, so it should rank higher than disconnect called once
            self.assertEqual(ranked[0]["callee_name"], "calculate_tax")
            self.assertGreaterEqual(ranked[0]["risk_score"], ranked[-1]["risk_score"])

    def test_function_aliases(self):
        """Test that function aliases produce identical output."""
        sample_sites = [
            {"function_name": "fn1", "caller_name": "a", "file_path": "x.py", "line_number": 1},
            {"function_name": "fn2", "caller_name": "b", "file_path": "y.py", "line_number": 2},
        ]
        res1 = rank_affected_call_sites(sample_sites)
        res2 = rank_by_risk(sample_sites)
        res3 = rank_risk(sample_sites)
        res4 = get_risk_ranked_call_sites(sample_sites)

        self.assertEqual(res1, res2)
        self.assertEqual(res1, res3)
        self.assertEqual(res1, res4)

    def test_format_risk_report(self):
        """Test format_risk_report produces formatted output with header, ranks, and details."""
        sample_sites = [
            {
                "file_path": "billing.py",
                "function_name": "calculate_tax",
                "callee_name": "calculate_tax",
                "line_number": 12,
                "caller_name": "process_order",
                "risk_score": 9.0,
                "risk_level": "HIGH",
                "risk_explanation": "Called 3 times with depth 3",
            }
        ]
        report = format_risk_report(sample_sites)
        self.assertIn("SAFEDEP RISK-RANKED CALL SITES", report)
        self.assertIn("#1", report)
        self.assertIn("calculate_tax", report)
        self.assertIn("billing.py:12", report)
        self.assertIn("HIGH", report)


if __name__ == "__main__":
    unittest.main()

