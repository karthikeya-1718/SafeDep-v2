# SafeDep

**SafeDep** is an automated API Breaking Change Detector and Test-Gated Repair Tool for Python projects. It inspects Python modules and packages using Python's standard `ast` (Abstract Syntax Tree) module, detects backward-incompatible API changes between versions, analyzes affected client call sites with risk scoring, and provides dual-phase automated repair: **Pre-Install Repair** for syntactical/signature changes and **Post-Install Repair** for behavioral/runtime issues.

---

## Key Features

- **Pure AST Parsing**: Operates safely without executing untrusted code or importing modules during static analysis.
- **Zero Core Dependencies**: Core diffing, call-graph analysis, and AST patch fallback rely strictly on the Python standard library (`ast`, `dataclasses`, `pathlib`, `argparse`). Compatible with Python 3.9+.
- **Comprehensive Breaking Change Detection**:
  - Removed public functions, classes, and class methods
  - Added required parameters without default values
  - Removed parameters (keyword or positional)
  - Removed default parameter values (making parameters required)
  - Parameter kind shifts (positional-or-keyword to keyword-only or positional-only)
  - Swapped / reordered positional parameters
  - Removed `*args` or `**kwargs`
  - Removed base classes from public classes
  - Removed public module-level constants
- **AST Call Graph & Impact Analysis**: Traces and locates every affected call site in client codebases with file paths, caller contexts, line numbers, and exact call expressions.
- **Explainable Risk Scoring**: Prioritizes call sites using call frequency and call chain depth (`risk_score = call_count * depth`), categorizing issues from LOW to CRITICAL.
- **Dual-Phase Automated Repair**:
  - **Pre-Install Repair**: Patches signature and syntactical breaking changes before upgrading the library.
  - **Post-Install Repair**: Runs test suite via `pytest` to detect behavioral changes, proposes candidate fixes via DeepSeek AI / AST engine, and applies strictly **test-gated** patches with automatic rollback if tests fail.

---

## Project Structure

```
SafeDep/
├── safedep/
│   ├── __init__.py           # Package exports and version metadata (v0.5.0)
│   ├── api_diff.py           # Core AST diffing engine (get_breaking_changes)
│   ├── call_graph.py         # Call graph builder & call-site locator
│   ├── patcher.py            # Shared patch engine (DeepSeek AI & AST fallback)
│   ├── risk_ranker.py        # Risk scoring & prioritization engine
│   ├── pre_install_repair.py # Pre-install repair orchestrator (signature-level)
│   ├── post_install_repair.py# Post-install repair orchestrator (test-gated)
│   └── utils.py              # AST helpers and report formatters
├── tests/
│   ├── __init__.py
│   ├── test_api_diff.py      # Unit tests for API diffing (16 tests)
│   ├── test_call_graph.py    # Unit tests for call graph (14 tests)
│   ├── test_patcher.py       # Unit tests for patch generator (18 tests)
│   ├── test_risk_ranker.py   # Unit tests for risk scoring (8 tests)
│   ├── test_pre_install_repair.py  # Unit tests for pre-install repair (8 tests)
│   └── test_post_install_repair.py # Unit tests for post-install repair (8 tests)
├── main.py                   # Unified CLI tool & 6-scenario demonstration
├── requirements.txt          # Optional development/test dependencies
└── README.md                 # Complete documentation
```

---

## Installation & Setup

1. **Clone or Navigate to SafeDep**:
   ```bash
   cd SafeDep
   ```

2. **Python Requirement**:
   Python 3.9 or higher (Python 3.10, 3.11, 3.12, 3.13, 3.14+ supported).

3. **Install Dependencies (Optional)**:
   ```bash
   pip install -r requirements.txt
   ```

4. **DeepSeek API Key (Optional)**:
   To enable AI-powered refactoring, set `DEEPSEEK_API_KEY`:
   ```bash
   # Linux / macOS
   export DEEPSEEK_API_KEY="your-api-key"

   # Windows PowerShell
   $env:DEEPSEEK_API_KEY="your-api-key"
   ```
   *Note: If no API key is set, SafeDep automatically uses its built-in deterministic AST refactoring engine.*

---

## CLI Commands Reference

SafeDep provides a clean CLI with three core commands and a built-in demo:

```bash
python main.py <command> [options]
```

### 1. `analyze` — Detect Breaking Changes & Risk
Compares two versions of a library and optionally maps affected call sites in a client application.

```bash
# Compare two library files
python main.py analyze path/to/v1.py path/to/v2.py

# Compare two packages/directories
python main.py analyze package_v1/ package_v2/

# Analyze impact on client application with call graph & risk ranking
python main.py analyze v1.py v2.py --client client_app.py

# Output results as structured JSON
python main.py analyze v1.py v2.py --client client_app.py --json
```

*Exit Codes:*
- `0`: Clean — no breaking changes found.
- `1`: Breaking changes detected.
- `2`: Error (invalid path or syntax error).

---

### 2. `pre-repair` — Pre-Install Repair Mode
Analyzes breaking changes, separates syntactical issues from behavioral issues, and generates refactoring patches before library installation.

```bash
# Preview proposed patches without modifying files (default)
python main.py pre-repair v1.py v2.py --client client_app.py --action report_only

# Apply patches to client files with automatic .bak backup
python main.py pre-repair v1.py v2.py --client client_app.py --action apply_only

# Apply patches and run `pip install <new_path>`
python main.py pre-repair v1.py v2.py --client client_app.py --action apply_and_install

# Interactive selection mode
python main.py pre-repair v1.py v2.py --client client_app.py --action interactive
```

---

### 3. `post-repair` — Post-Install Repair Mode
Assumes the new library is already installed. Runs the client project's test suite via `pytest`, identifies remaining runtime/behavioral incompatibilities, generates candidate fixes, and strictly test-gates every patch.

```bash
# Run test-gated repair on tests in tests/
python main.py post-repair --test-target tests/

# Target specific client file and test suite
python main.py post-repair --test-target tests/test_app.py --client src/app.py

# Set maximum retry attempts per issue (default: 2)
python main.py post-repair --test-target tests/ --client src/ --max-retries 2

# Output results as JSON
python main.py post-repair --test-target tests/ --json
```

---

### 4. `demo` — Built-in 6-Scenario Automated Demonstration
Runs an end-to-end live demonstration showcasing:
1. API diff detection (breaking changes)
2. Backward-compatible update detection
3. AST call graph impact analysis
4. Risk scoring and prioritization
5. Pre-Install Repair mode (signature patching)
6. Post-Install Repair mode (test-gated behavioral repair)

```bash
# Run demo via command or simply without arguments
python main.py demo
python main.py
```

---

## Syntactical vs. Behavioral Handling

SafeDep divides breaking changes into two distinct categories:

| Dimension | Syntactical / Signature-Level Issues | Behavioral / Runtime Issues |
| :--- | :--- | :--- |
| **Phase Handled** | **Pre-Install Repair** (before installation) | **Post-Install Repair** (after installation) |
| **Detection Source** | Static AST Diff of library definitions + Call Graph | Test suite execution (`pytest`) failure traces |
| **Detection Method** | Pure AST static analysis (no code execution) | Dynamic test execution & assertion inspection |
| **Included Changes** | - Removed functions, classes, or methods<br>- Added required parameters<br>- Removed parameters<br>- Removed default parameter values<br>- Reordered positional parameters<br>- Changed parameter kinds (keyword-only) | - Functions exist with identical signatures<br>- Changed return values or return formats<br>- Altered calculation algorithms<br>- New internal exceptions or edge cases<br>- State and side-effect changes |
| **Fix Verification** | AST structure check / unified diff inspection | **Strictly Test-Gated**: patch is accepted only if pytest confirms tests pass; auto-reverted on failure |
| **Max Retries** | Single-pass generation | Up to **2 retries per issue** with test feedback |

---

## Programmatic API Usage

SafeDep can also be integrated directly as a Python library:

### 1. Detecting Breaking Changes (`safedep.api_diff`)
```python
from safedep.api_diff import get_breaking_changes
from safedep.utils import format_diff_report

diff = get_breaking_changes("v1.py", "v2.py")
if diff["breaking_changes_found"]:
    print(f"Total breaking changes: {diff['summary']['total']}")
    print(format_diff_report(diff))
```

### 2. Mapping Affected Call Sites (`safedep.call_graph`)
```python
from safedep.call_graph import get_affected_call_sites, format_call_sites_report

sites = get_affected_call_sites("client_project/", diff)
print(format_call_sites_report(sites))
```

### 3. Risk Ranking (`safedep.risk_ranker`)
```python
from safedep.risk_ranker import rank_affected_call_sites, format_risk_report

# risk_score = call_count * depth
ranked = rank_affected_call_sites(sites, project_path="client_project/")
print(format_risk_report(ranked))
```

### 4. Patch Generation (`safedep.patcher`)
```python
from safedep.patcher import propose_patch

fixed_call = propose_patch(
    code_snippet="fetch_user(user_id, timeout=10)",
    breaking_change_info={
        "breaking_change": "Parameter 'timeout' was removed",
        "old_signature": "def fetch_user(user_id, timeout=10)",
        "new_signature": "def fetch_user(user_id)",
    },
)
# Returns: "fetch_user(user_id)"
```

### 5. Pre-Install Repair (`safedep.pre_install_repair`)
```python
from safedep.pre_install_repair import run_pre_install_repair

report = run_pre_install_repair(
    old_path="v1.py",
    new_path="v2.py",
    client_path="client_app.py",
    action="apply_only",
)
print(f"Syntactical fixed: {report.syntactical_count}")
print(f"Behavioral deferred: {report.behavioral_count}")
```

### 6. Post-Install Repair (`safedep.post_install_repair`)
```python
from safedep.post_install_repair import run_post_install_repair, format_post_install_report

post_report = run_post_install_repair(
    test_target="tests/",
    client_path="src/client.py",
    max_retries=2,
)
print(format_post_install_report(post_report))
```

---

## Running Unit Tests

Run the full automated test suite (72 unit tests across 6 test modules):

```bash
# Run all unit tests via unittest discover
python -m unittest discover -s tests -p "test_*.py"

# Or run individual test modules
python tests/test_api_diff.py
python tests/test_call_graph.py
python tests/test_risk_ranker.py
python tests/test_patcher.py
python tests/test_pre_install_repair.py
python tests/test_post_install_repair.py
```

---

## Demonstration Guide

To demonstrate SafeDep end-to-end:

1. **Run the Automated Live Demo**:
   ```bash
   python main.py
   ```
2. **Inspect the 6 Progressive Scenarios**:
   - **Scenario 1**: High-fidelity detection of removed functions, removed methods, and signature alterations.
   - **Scenario 2**: Detection of backward-compatible additions (additive parameters with defaults).
   - **Scenario 3**: AST call graph tracing locating affected call expressions in client code.
   - **Scenario 4**: Risk prioritization ranking call sites by depth and frequency.
   - **Scenario 5**: Pre-Install Repair generating signature refactoring diffs.
   - **Scenario 6**: Post-Install Repair executing pytest, catching behavioral issues, and applying test-gated fixes.

---

## License

MIT License.
