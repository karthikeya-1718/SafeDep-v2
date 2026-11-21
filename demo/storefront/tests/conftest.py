"""Pytest fixtures for Storefront test suite."""

import sys
from pathlib import Path
import pytest

# Ensure storefront root is in sys.path
storefront_dir = str(Path(__file__).resolve().parent.parent)
if storefront_dir not in sys.path:
    sys.path.insert(0, storefront_dir)

from app import create_app
from app.data import reset_store_state


@pytest.fixture(autouse=True)
def reset_state_before_each_test():
    """Reset all in-memory store state before every test."""
    reset_store_state()
    yield
    reset_store_state()


@pytest.fixture
def app():
    """Create configured test application."""
    test_app = create_app()
    test_app.config["TESTING"] = True
    return test_app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()
