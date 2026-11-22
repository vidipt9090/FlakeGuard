"""Shared test guards."""

import httpx
import pytest


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """A test must never reach the real network with the developer's own GitHub token.

    Real HTTP transports refuse; ``httpx.MockTransport`` is untouched, so tests that exercise GitHub
    code give their client a mock transport. (An earlier version of the quarantine test opened two
    real issues on the demo repository because the backend found a ``gh`` login. See docs/DECISIONS.md M6-2.)
    """

    def refuse(self, request):
        raise AssertionError(f"this test tried a real HTTP request to {request.url}; give the client a MockTransport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
