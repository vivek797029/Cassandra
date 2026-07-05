"""Shared test plumbing — real store isolation.

Why this exists: `services.copilot.config.get_settings()` is process-cached and
`services.copilot.store.get_store()` is a process-wide singleton. The
`os.environ.setdefault("ARGUS_DB", ...)` lines at the top of individual test
modules therefore only ever took effect for whichever module the process
imported *first*; after that, every module silently shared one store. Worse,
when ARGUS_DB was already exported (as `scripts/dev_setup.sh` does), the
setdefault was a no-op and test writes — band-cache markers, promoted thetas —
leaked into the *shared, persistent* dev DB, corrupting the next run's serving
state (observed: /v1/forecasts returning placeholder bands 0.111/0.222).

This autouse fixture makes the intended isolation real: each test module gets
a fresh throwaway SQLite file, and the settings cache + store singleton are
reset on entry and exit so no state crosses module or run boundaries.

Note: when DATABASE_URL is set (the PostgreSQL CI job), the store backend is
PostgreSQL and ARGUS_DB is ignored; modules then share the service database as
before. Tests that write to the store must clean up after themselves (see
tests/test_bands.py) so they stay safe on both backends.
"""
import os

import pytest


@pytest.fixture(autouse=True, scope="module")
def _isolated_store_per_module(request, tmp_path_factory):
    from services.copilot import config, store

    prev = os.environ.get("ARGUS_DB")
    db = tmp_path_factory.mktemp("argus_store") / f"{request.module.__name__}.db"
    os.environ["ARGUS_DB"] = str(db)
    config.reset_settings_cache()
    store.STORE = None
    yield
    if prev is None:
        os.environ.pop("ARGUS_DB", None)
    else:
        os.environ["ARGUS_DB"] = prev
    config.reset_settings_cache()
    store.STORE = None
