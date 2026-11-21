"""Catalog module."""

from shopkit import execute_query

# Module-level inventory query executed at startup
INVENTORY = execute_query("SELECT id, stock FROM inventory", timeout=10)
