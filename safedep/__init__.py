"""SafeDep: Automated API Breaking Change Detector for Python.

SafeDep inspects Python modules and packages using the AST module to extract
public functions and classes, detecting incompatible changes across versions.
"""

from .api_diff import get_breaking_changes
from .call_graph import (
    CallGraph,
    CallSite,
    build_call_graph,
    find_affected_call_sites,
    format_call_sites_report,
    get_affected_call_sites,
)
from .patcher import propose_patch
from .post_install_repair import (
    PostInstallIssue,
    PostInstallRepairReport,
    TestSuiteResult,
    format_post_install_report,
    identify_test_failures,
    run_post_install_repair,
    run_pytest,
)
from .pre_install_repair import (
    PreInstallRepairReport,
    RepairIssue,
    analyze_pre_install_issues,
    apply_fixes,
    format_pre_install_report,
    run_pre_install_repair,
)
from .risk_ranker import (
    format_risk_report,
    get_risk_ranked_call_sites,
    rank_affected_call_sites,
    rank_by_risk,
    rank_call_sites,
    rank_risk,
    score_and_rank_call_sites,
)
from .utils import (
    extract_public_snapshot,
    format_diff_report,
    parse_source_to_ast,
)

__version__ = "0.5.0"
__author__ = "SafeDep Team"
__all__ = [
    "get_breaking_changes",
    "get_affected_call_sites",
    "find_affected_call_sites",
    "build_call_graph",
    "format_call_sites_report",
    "propose_patch",
    "rank_affected_call_sites",
    "rank_by_risk",
    "rank_risk",
    "get_risk_ranked_call_sites",
    "rank_call_sites",
    "score_and_rank_call_sites",
    "format_risk_report",
    "PreInstallRepairReport",
    "RepairIssue",
    "analyze_pre_install_issues",
    "format_pre_install_report",
    "apply_fixes",
    "run_pre_install_repair",
    "PostInstallIssue",
    "PostInstallRepairReport",
    "TestSuiteResult",
    "run_post_install_repair",
    "format_post_install_report",
    "run_pytest",
    "identify_test_failures",
    "CallGraph",
    "CallSite",
    "format_diff_report",
    "extract_public_snapshot",
    "parse_source_to_ast",
]

