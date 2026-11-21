"""
Helpers shared by the V2 test scripts (offline: every HTTP call goes through a MockTransport
that fails loudly on any host the test did not expect).
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Callable

import httpx

TESTS_DATA = Path(__file__).resolve().parent / "tests_data"


def use_temp_database() -> str:
    """Point DATABASE_URL at a new temporary SQLite file. Call BEFORE importing database/main."""
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{handle.name}"
    return handle.name


def fixture_json(name: str):
    return json.loads((TESTS_DATA / name).read_text(encoding="utf-8"))


def fixture_text(name: str) -> str:
    return (TESTS_DATA / name).read_text(encoding="utf-8")


class Checker:
    def __init__(self, title: str):
        self.total = 0
        self.passed = 0
        print("=" * 70)
        print(title)
        print("=" * 70)

    def __call__(self, condition, name: str) -> None:
        self.total += 1
        if condition:
            self.passed += 1
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            raise AssertionError(f"Test failed: {name}")

    def section(self, name: str) -> None:
        print(f"\n--- {name} ---")

    def done(self, label: str) -> None:
        print("\n" + "=" * 70)
        print(f"ALL {self.total} {label} TESTS PASSED! ({self.passed}/{self.total})")
        print("=" * 70)


def mock_client(handlers: dict[str, Callable[[httpx.Request], httpx.Response]], seen: list | None = None) -> httpx.Client:
    """httpx.Client whose requests are routed by host; an unknown host raises (never goes online)."""

    def route(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        handler = handlers.get(request.url.host)
        if handler is None:
            raise AssertionError(f"Unexpected outgoing request to {request.url.host}")
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(route))
