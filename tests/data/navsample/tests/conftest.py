"""Fixtures for the navigator sample project (not collected by pytest)."""

import pytest


@pytest.fixture
def prices():
    return [1.0, 2.0]


@pytest.fixture(scope="module")
def shared_cart():
    return []
