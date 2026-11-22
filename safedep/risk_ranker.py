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
    tier_ordering: Optional[bool] = None,
    library_name: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Assign risk scores to affected call sites and return them sorted from highest to lowest risk.

    Scoring is based on:
      1. Call count: Number of times the broken function is called across breaking call sites.
      2. Call chain depth: Depth of the function in the execution call chain (BFS from entry points).

    Simple and Explainable Formula:
      risk_score = call_count * depth

    Args:
        affected_call_sites: List of call site dicts from `get_affected_call_sites()`.
        call_graph: Optional CallGraph instance.
        project_path: Optional path to project directory or file to build call graph.
        tier_ordering: Whether to use startup-first tier ordering. Defaults to True when library_name
            is provided or present on sites, False for legacy calls.
        library_name: Optional library name.

    Returns:
        list[dict]: Enriched call site dictionaries sorted by risk/tier.
    """
    if not affected_call_sites:
        return []

    # Step 1: Attempt to build CallGraph if project_path is supplied and build_call_graph is available
    active_graph = call_graph
    if active_graph is None and project_path is not None and build_call_graph is not None:
        try:
            active_graph = build_call_graph(project_path, library_name=library_name)
        except Exception:
            active_graph = None

    # Step 2: Calculate call frequency strictly over sites that really break
    call_counts: dict[str, int] = defaultdict(int)
    for site in affected_call_sites:
        fn_name = site.get("callee_name") or site.get("callee") or str(site.get("function_name", "unknown"))
        call_counts[fn_name] += 1

    # Map number of distinct callers reaching each enclosing function
    distinct_callers: dict[str, set[str]] = defaultdict(set)
    if active_graph is not None and hasattr(active_graph, "all_call_sites"):
        for s in active_graph.all_call_sites:
            c_name = getattr(s, "caller_name", "")
            fn = getattr(s, "callee_name", "")
            if fn and c_name:
                distinct_callers[fn].add(c_name)

    # Step 3: Compute call chain depth for all functions
    depth_map = compute_call_depths(affected_call_sites, call_graph=active_graph)

    # Determine if tier ordering should be used
    if tier_ordering is None:
        tier_ordering = bool(library_name or any(s.get("library_name") for s in affected_call_sites))

    # Step 4: Enrich each call site with when_fails, fixability, call_count, depth, risk_score
    ranked_sites: list[dict[str, Any]] = []

    for site in affected_call_sites:
        site_copy = dict(site)

        caller = site.get("caller_name") or site.get("caller") or "<module>"
        callee = site.get("callee_name") or site.get("callee") or str(site.get("function_name", "unknown"))

        # 1. Determine call count
        count = call_counts.get(callee, 1)

        # 2. Determine call chain depth
        if callee in depth_map:
            depth = depth_map[callee]
        elif caller in depth_map:
            depth = depth_map[caller] + 1
        else:
            depth = 1 + (caller.count(".") if caller != "<module>" else 0)

        depth = max(1, depth)

        # 3. Simple, explainable risk score calculation:
        score = float(count * depth)
        level = get_risk_level(score)

        explanation = (
            f"Called {count} time(s) across codebase with call chain depth {depth} "
            f"(risk score = {count} x {depth} = {score:.1f})"
        )

        when_fails = "startup" if caller == "<module>" else "on_call"

        # Fixability: auto for signature changes judged breaks, manual for removals, review for uncertain
        compat = site.get("compatibility", "breaks")
        is_removal = site.get("is_removal", False)
        if is_removal:
            fixability = "manual"
        elif compat == "uncertain":
            fixability = "review"
        else:
            fixability = "auto"

        num_callers = len(distinct_callers.get(caller, set()))

        site_copy["call_count"] = count
        site_copy["depth"] = depth
        site_copy["risk_score"] = score
        site_copy["risk_level"] = level
        site_copy["risk_explanation"] = explanation
        site_copy["when_fails"] = when_fails
        site_copy["fixability"] = fixability
        site_copy["num_distinct_callers"] = num_callers

        ranked_sites.append(site_copy)

    # Step 5: Sort
    if tier_ordering:
        # Force CRITICAL for every startup-tier site regardless of score
        for s in ranked_sites:
            if s.get("when_fails") == "startup":
                s["risk_level"] = "CRITICAL"
        ranked_sites.sort(
            key=lambda s: (
                0 if s["when_fails"] == "startup" else 1,
                -s["risk_score"],
                -s.get("num_distinct_callers", 0),
                -s["depth"],
                str(s.get("file_path", "")),
                int(s.get("line_number", 0)),
            )
        )
    else:
        # Legacy sorting preserved for callers without library binding
        ranked_sites.sort(
            key=lambda s: (
                -s["risk_score"],
                -s["call_count"],
                -s["depth"],
                str(s.get("file_path", "")),
                int(s.get("line_number", 0)),
            )
        )

    # Forward unaffected sites attribute if present
    unaffected = getattr(affected_call_sites, "unaffected", None)
    if unaffected is not None:
        try:
            from .call_graph import AffectedCallSitesList
            return AffectedCallSitesList(ranked_sites, unaffected=unaffected)
        except ImportError:
            pass

    return ranked_sites


# Convenient function aliases
rank_by_risk = rank_affected_call_sites
rank_risk = rank_affected_call_sites
get_risk_ranked_call_sites = rank_affected_call_sites
rank_call_sites = rank_affected_call_sites
score_and_rank_call_sites = rank_affected_call_sites


def format_risk_report(
    ranked_call_sites: list[dict[str, Any]],
    title: str = "SafeDep Risk-Ranked Call Sites",
    unaffected_count: Optional[int] = None,
) -> str:
    """Format the risk-ranked call sites into an attractive, clear terminal report."""
    border = "=" * 70
    sub_border = "-" * 70
    total = len(ranked_call_sites)

    unaffected = getattr(ranked_call_sites, "unaffected", None)
    if unaffected_count is None and unaffected is not None:
        unaffected_count = len(unaffected)

    lines = [
        border,
        f"  {title.upper()}",
        border,
        f"Total Call Sites Analyzed: {total}",
    ]

    if unaffected_count is not None:
        checked = total + unaffected_count
        lines.append(f"Checked {checked} call site(s): {total} breaking, {unaffected_count} still fit the new version.")

    lines.extend([
        "Scoring Methodology: Risk Score = (Call Frequency) x (Call Chain Depth)",
        sub_border,
    ])

    if not total:
        lines.append("[OK] No affected call sites to rank.")
        lines.append(border)
        return "\n".join(lines)

    lines.append(f"{'RANK':<5} | {'RISK':<8} | {'WHEN':<8} | {'FUNCTION':<24} | {'LOCATION':<22} | {'FIX':<6}")
    lines.append("-" * 80)

    for idx, s in enumerate(ranked_call_sites, 1):
        callee = s.get("callee_name") or s.get("callee") or str(s.get("function_name", "unknown"))
        file_name = Path(s.get("file_path", "unknown")).name
        line_no = s.get("line_number", "?")
        location = f"{file_name}:{line_no}"
        level = s.get("risk_level", "LOW")
        when = s.get("when_fails", "on_call")
        fix = s.get("fixability", "auto")

        lines.append(f"#{idx:<4} | {level:<8} | {when:<8} | {callee:<24} | {location:<22} | {fix:<6}")

    lines.append(border)
    return "\n".join(lines)

