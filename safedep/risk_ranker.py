"""SafeDep Risk Ranker Module.

Ranks affected call sites by breaking change impact risk.
Assigns a risk score to each affected call site based on:
  1. Call Frequency (call_count): How many times the broken function is invoked.
  2. Call Chain Depth (depth): How deep the function is in the execution call chain.

Formula:
  risk_score = call_count * depth

Explanation:
  - Functions with high call frequency affect a wider blast radius of the codebase.
  - Functions located deeper in the call chain can propagate hidden runtime errors
    across multiple layers of abstraction and are harder to trace and debug.
  - The combination (call_count * depth) provides a simple, explainable metric
    where widespread, deeply integrated dependencies are prioritized first.
"""

from __future__ import annotations

import os
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional, Union

# Optional import of call graph utilities if available
try:
    from .call_graph import CallGraph, build_call_graph
except ImportError:
    CallGraph = None  # type: ignore
    build_call_graph = None  # type: ignore


def compute_call_depths(
    call_sites: list[dict[str, Any]],
    call_graph: Optional[Any] = None,
) -> dict[str, int]:
    """Compute call chain depth for each function using Breadth-First Search (BFS).

    Entry points (e.g. `<module>`, `main`, route handlers) have depth 1.
    Each subsequent call down the call chain increments depth by 1.

    Args:
        call_sites: List of affected call site dictionaries.
        call_graph: Optional pre-built CallGraph object.

    Returns:
        dict[str, int]: Mapping from function/symbol name to call chain depth (>= 1).
    """
    adjacency: dict[str, set[str]] = defaultdict(set)
    all_nodes: set[str] = set()

    # 1. If a full CallGraph is provided, build graph from its full callers map
    if call_graph is not None and hasattr(call_graph, "callers"):
        for caller, sites in call_graph.callers.items():
            all_nodes.add(caller)
            for s in sites:
                callee = getattr(s, "callee_name", str(s))
                adjacency[caller].add(callee)
                all_nodes.add(callee)

    # 2. Add edges from the affected call sites
    for s in call_sites:
        caller = s.get("caller_name") or s.get("caller") or "<module>"
        callee = s.get("callee_name") or s.get("callee") or str(s.get("function_name", "unknown"))
        adjacency[caller].add(callee)
        all_nodes.add(caller)
        all_nodes.add(callee)

    if not all_nodes:
        return {}

    # 3. Compute in-degree to find entry point roots (in-degree == 0 or '<module>')
    in_degree: dict[str, int] = {node: 0 for node in all_nodes}
    for caller, callees in adjacency.items():
        for c in callees:
            in_degree[c] = in_degree.get(c, 0) + 1

    entry_points = [node for node in all_nodes if in_degree[node] == 0 or node == "<module>"]
    if not entry_points:
        entry_points = list(all_nodes)

    # 4. BFS traversal from entry points
    depths: dict[str, int] = {}
    queue: deque[str] = deque()

    for ep in entry_points:
        # Base depth: 1 for module / root functions, or 1 + number of dots in scope
        base_depth = 1 + (ep.count(".") if ep != "<module>" else 0)
        depths[ep] = base_depth
        queue.append(ep)

    while queue:
        current = queue.popleft()
        current_depth = depths[current]
        for neighbor in adjacency.get(current, []):
            new_depth = current_depth + 1
            if neighbor not in depths or new_depth < depths[neighbor]:
                depths[neighbor] = new_depth
                queue.append(neighbor)

    return depths


def get_risk_level(score: float) -> str:
    """Categorize risk score into a human-readable level."""
    if score >= 10.0:
        return "CRITICAL"
    if score >= 5.0:
        return "HIGH"
    if score >= 2.0:
        return "MEDIUM"
    return "LOW"


def rank_affected_call_sites(
    affected_call_sites: list[dict[str, Any]],
    call_graph: Optional[Any] = None,
    project_path: Optional[Union[str, Path]] = None,
) -> list[dict[str, Any]]:
    """Assign risk scores to affected call sites and return them sorted from highest to lowest risk.

    Scoring is based on:
      1. Call count: Number of times the broken function is called across call sites.
      2. Call chain depth: Depth of the function in the execution call chain (BFS from entry points).

    Simple and Explainable Formula:
      risk_score = call_count * depth

    Args:
        affected_call_sites: List of call site dicts from `get_affected_call_sites()`.
        call_graph: Optional CallGraph instance.
        project_path: Optional path to project directory or file to build call graph.

    Returns:
        list[dict]: New list of enriched call site dictionaries sorted from
            highest risk to lowest risk. Each item contains:
            - 'risk_score': float / int (call_count * depth)
            - 'call_count': int (how many times the function is called)
            - 'depth': int (call chain depth >= 1)
            - 'risk_level': str ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')
            - 'risk_explanation': str (plain English explanation of score)
            - All original call site fields (file_path, function_name, line_number, etc.)
    """
    if not affected_call_sites:
        return []

    # Step 1: Attempt to build CallGraph if project_path is supplied and build_call_graph is available
    active_graph = call_graph
    if active_graph is None and project_path is not None and build_call_graph is not None:
        try:
            active_graph = build_call_graph(project_path)
        except Exception:
            active_graph = None

    # Step 2: Calculate call frequency (how many times each function is called)
    call_counts: dict[str, int] = defaultdict(int)
    for site in affected_call_sites:
        fn_name = site.get("callee_name") or site.get("callee") or str(site.get("function_name", "unknown"))
        call_counts[fn_name] += 1

    # If active call graph is available, count overall occurrences in the project
    if active_graph is not None and hasattr(active_graph, "all_call_sites"):
        project_counts: dict[str, int] = defaultdict(int)
        for s in active_graph.all_call_sites:
            callee = getattr(s, "callee_name", "")
            if callee:
                project_counts[callee] += 1
        for fn in call_counts:
            if fn in project_counts:
                call_counts[fn] = max(call_counts[fn], project_counts[fn])

    # Step 3: Compute call chain depth for all functions
    depth_map = compute_call_depths(affected_call_sites, call_graph=active_graph)

    # Step 4: Enrich each call site with call_count, depth, risk_score, and explanation
    ranked_sites: list[dict[str, Any]] = []

    for site in affected_call_sites:
        site_copy = dict(site)

        caller = site.get("caller_name") or site.get("caller") or "<module>"
        callee = site.get("callee_name") or site.get("callee") or str(site.get("function_name", "unknown"))

        # 1. Determine call count
        count = call_counts.get(callee, 1)

        # 2. Determine call chain depth
        # Depth of the callee from BFS, or caller depth + 1, with a minimum of 1
        if callee in depth_map:
            depth = depth_map[callee]
        elif caller in depth_map:
            depth = depth_map[caller] + 1
        else:
            # Fallback based on caller scope depth
            depth = 1 + (caller.count(".") if caller != "<module>" else 0)

        depth = max(1, depth)

        # 3. Simple, explainable risk score calculation:
        # risk_score = call_count * depth
        score = float(count * depth)
        level = get_risk_level(score)

        explanation = (
            f"Called {count} time(s) across codebase with call chain depth {depth} "
            f"(risk score = {count} x {depth} = {score:.1f})"
        )

        site_copy["call_count"] = count
        site_copy["depth"] = depth
        site_copy["risk_score"] = score
        site_copy["risk_level"] = level
        site_copy["risk_explanation"] = explanation

        ranked_sites.append(site_copy)

    # Step 5: Sort from highest risk to lowest risk
    # Primary key: risk_score descending
    # Secondary key: call_count descending
    # Tertiary key: depth descending
    # Final tie-breaker: file_path and line_number ascending for deterministic ordering
    ranked_sites.sort(
        key=lambda s: (
            -s["risk_score"],
            -s["call_count"],
            -s["depth"],
            str(s.get("file_path", "")),
            int(s.get("line_number", 0)),
        )
    )

    return ranked_sites


# Convenient function aliases
rank_by_risk = rank_affected_call_sites
rank_risk = rank_affected_call_sites
get_risk_ranked_call_sites = rank_affected_call_sites
rank_call_sites = rank_affected_call_sites
score_and_rank_call_sites = rank_affected_call_sites


def format_risk_report(ranked_call_sites: list[dict[str, Any]], title: str = "SafeDep Risk-Ranked Call Sites") -> str:
    """Format the risk-ranked call sites into an attractive, clear terminal report."""
    border = "=" * 70
    sub_border = "-" * 70
    total = len(ranked_call_sites)

    lines = [
        border,
        f"  {title.upper()}",
        border,
        f"Total Call Sites Analyzed: {total}",
        "Scoring Methodology: Risk Score = (Call Frequency) x (Call Chain Depth)",
        sub_border,
    ]

    if not total:
        lines.append("[OK] No affected call sites to rank.")
        lines.append(border)
        return "\n".join(lines)

    lines.append(f"{'RANK':<5} | {'RISK':<8} | {'SCORE':<6} | {'FUNCTION':<20} | {'LOCATION':<24}")
    lines.append("-" * 70)

    for idx, s in enumerate(ranked_call_sites, 1):
        callee = s.get("callee_name") or s.get("callee") or str(s.get("function_name", "unknown"))
        file_name = Path(s.get("file_path", "unknown")).name
        line_no = s.get("line_number", "?")
        location = f"{file_name}:{line_no}"
        score = s.get("risk_score", 0.0)
        level = s.get("risk_level", "LOW")

        lines.append(f"#{idx:<4} | {level:<8} | {score:<6.1f} | {callee:<20} | {location:<24}")
        lines.append(f"       -> Details: {s.get('risk_explanation', '')}")

    lines.append(border)
    return "\n".join(lines)

