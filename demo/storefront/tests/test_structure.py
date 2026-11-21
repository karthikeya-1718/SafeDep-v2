import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SHOPKIT = {"fetch_user_profile", "execute_query", "format_invoice",
           "set_notification_channel", "legacy_discount", "calculate_total"}

# (shopkit function, file under app/, enclosing function, n positional args,
#  keyword names)
EXPECTED = sorted([
    ("fetch_user_profile", "helpers/user_helpers.py", "load_user_record", 1, ()),
    ("fetch_user_profile", "services/user_service.py", "get_display_name", 1, ()),
    ("fetch_user_profile", "services/user_service.py", "update_preferences", 1, ()),
    ("fetch_user_profile", "services/order_service.py", "place_order", 1, ()),
    ("fetch_user_profile", "services/order_service.py", "get_order_history", 1, ()),
    ("fetch_user_profile", "services/notification_service.py", "send_order_confirmation", 1, ()),
    ("execute_query", "catalog.py", "<module>", 1, ("timeout",)),
    ("execute_query", "helpers/db_helpers.py", "fetch_order_history", 1, ("timeout",)),
    ("execute_query", "helpers/db_helpers.py", "fetch_stock_levels", 1, ("timeout",)),
    ("execute_query", "helpers/db_helpers.py", "fetch_featured_products", 1, ()),
    ("execute_query", "services/search_service.py", "search_products", 1, ()),
    ("format_invoice", "services/order_service.py", "create_invoice", 2, ()),
    ("set_notification_channel", "services/notification_service.py", "send_order_confirmation", 0, ()),
    ("set_notification_channel", "services/user_service.py", "update_preferences", 1, ()),
    ("legacy_discount", "services/pricing_service.py", "apply_promo", 2, ()),
    ("calculate_total", "services/pricing_service.py", "cart_total", 1, ()),
])

MIN_HOPS = {"load_user_record": 2, "send_order_confirmation": 2,
            "create_invoice": 2, "fetch_order_history": 2,
            "fetch_stock_levels": 2}


def _files():
    return sorted(APP.rglob("*.py"))


def _collect():
    found = []
    for path in _files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names, modules = {}, set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "shopkit":
                for a in node.names:
                    names[a.asname or a.name] = a.name
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "shopkit":
                        modules.add(a.asname or a.name)
        rel = path.relative_to(APP).as_posix()

        def visit(node, scope):
            for child in ast.iter_child_nodes(node):
                s = child.name if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
                if isinstance(child, ast.Call):
                    fn, target = child.func, None
                    if isinstance(fn, ast.Name) and fn.id in names:
                        target = names[fn.id]
                    elif (isinstance(fn, ast.Attribute)
                          and isinstance(fn.value, ast.Name)
                          and fn.value.id in modules):
                        target = fn.attr
                    if target in SHOPKIT:
                        found.append((target, rel, scope, len(child.args),
                                      tuple(sorted(k.arg for k in child.keywords))))
                visit(child, s)

        visit(tree, "<module>")
    return sorted(found)


def _hops_from_routes():
    defs, routes = {}, set()
    for path in _files():
        rel = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                called = set()
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        f = sub.func
                        if isinstance(f, ast.Name):
                            called.add(f.id)
                        elif isinstance(f, ast.Attribute):
                            called.add(f.attr)
                defs.setdefault(node.name, set()).update(called)
                if rel.startswith("routes/") and node.decorator_list:
                    routes.add(node.name)
    dist = {r: 0 for r in routes}
    queue = list(routes)
    while queue:
        cur = queue.pop(0)
        for nxt in defs.get(cur, ()):
            if nxt in defs and nxt not in dist:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    return dist


def test_shopkit_call_sites_match_spec():
    assert _collect() == EXPECTED


def test_import_styles():
    src = {p.relative_to(APP).as_posix(): p.read_text(encoding="utf-8")
           for p in _files()}
    pricing = src["services/pricing_service.py"]
    assert "import shopkit" in pricing
    assert "calculate_total as" in pricing
    assert any("from shopkit import" in s
               for k, s in src.items() if k != "services/pricing_service.py")


def test_startup_call_is_module_level():
    tree = ast.parse((APP / "catalog.py").read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
               for n in tree.body)


def test_call_chains_are_layered():
    dist = _hops_from_routes()
    containers = {e[2] for e in EXPECTED if e[2] != "<module>"}
    for fn in containers:
        assert fn in dist, f"{fn} is not reachable from any route"
    for fn, hops in MIN_HOPS.items():
        assert dist[fn] >= hops, f"{fn} is only {dist[fn]} hops from a route"


def test_no_dynamic_calls_and_no_safedep_import():
    for p in _files():
        text = p.read_text(encoding="utf-8")
        for bad in ("getattr(", "importlib", "__import__", "safedep"):
            assert bad not in text, f"{bad} found in {p.name}"
