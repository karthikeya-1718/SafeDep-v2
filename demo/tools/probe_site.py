"""Probe storefront site inside the target Python environment.

Imports create_app from the target project and outputs a single JSON object:
{"startup_ok": bool, "error": str | null, "routes": [{"method", "path", "status", "error"}]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def probe(project_dir: Path) -> dict:
    """Probe storefront application startup and routes."""
    # Ensure project_dir is in sys.path
    resolved_proj = project_dir.resolve()
    if str(resolved_proj) not in sys.path:
        sys.path.insert(0, str(resolved_proj))

    # Attempt to import create_app and instantiate the application
    try:
        from app import create_app  # type: ignore[import-not-found]
        application = create_app()
    except Exception as exc:
        return {
            "startup_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "routes": [],
        }

    # Application started successfully
    application.testing = False  # non-testing mode so server errors return 500

    last_error: list[str | None] = [None]

    # Attempt to register error handler / signal to capture exceptions
    try:
        from flask import got_request_exception
        def on_exc(sender, exception, **extra):
            last_error[0] = f"{type(exception).__name__}: {exception}"
        got_request_exception.connect(on_exc, application)
    except Exception:
        pass

    @application.errorhandler(Exception)
    def catch_all_exc(e):
        last_error[0] = f"{type(e).__name__}: {e}"
        # Let Flask return 500
        return ("Internal Server Error", 500)

    client = application.test_client()

    probe_specs = [
        ("GET", "/", None),
        ("GET", "/products", None),
        ("GET", "/product/1", None),
        ("GET", "/cart", None),
        ("POST", "/cart/add", {"product_id": 1, "quantity": 1}),
        ("POST", "/cart/promo", {"promo_code": "SAVE10"}),
        ("GET", "/checkout", None),
        ("POST", "/checkout", {}),
        ("GET", "/orders", None),
        ("GET", "/profile", None),
        ("POST", "/profile", {"channel": "email"}),
    ]

    routes_result = []

    for method, path, data in probe_specs:
        last_error[0] = None
        try:
            if method == "GET":
                resp = client.get(path)
            elif method == "POST":
                resp = client.post(path, data=data or {})
            else:
                resp = client.open(path, method=method)

            status = resp.status_code
            err = last_error[0]
            if status >= 400 and not err:
                err = f"HTTP {status}"

            routes_result.append({
                "method": method,
                "path": path,
                "status": status,
                "error": err,
            })
        except Exception as req_exc:
            routes_result.append({
                "method": method,
                "path": path,
                "status": 500,
                "error": f"{type(req_exc).__name__}: {req_exc}",
            })

    return {
        "startup_ok": True,
        "error": None,
        "routes": routes_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe storefront application inside target environment")
    parser.add_argument("--project", default="demo/storefront", help="Path to storefront project root")
    args = parser.parse_args()

    result = probe(Path(args.project))
    print(json.dumps(result))
    return 0 if result["startup_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
