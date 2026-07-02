"""Task 69 — self-contained load-test harness.

Boots the Copilot API with uvicorn on a free port, waits for /readyz, then runs
Locust headless (100 users, mixed intents) against it and propagates Locust's
exit code (the locustfile's `quitting` gate fails the run if cached p99 ≥ 1s or
any request failed). Used as the CI load gate and for local verification.

    python benchmarks/run_locust.py            # 100 users, 20s
    LOCUST_USERS=100 LOCUST_RUNTIME=30s python benchmarks/run_locust.py

Uses sys.executable for both child processes, so it runs identically in CI and
in a local virtualenv as long as `locust` and `uvicorn` are installed.
"""
from __future__ import annotations
import os, sys, socket, subprocess, time, urllib.request, signal, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HERE = os.path.dirname(os.path.abspath(__file__))

USERS = os.environ.get("LOCUST_USERS", "100")
SPAWN = os.environ.get("LOCUST_SPAWN", "50")
RUNTIME = os.environ.get("LOCUST_RUNTIME", "20s")
WORKERS = os.environ.get("API_WORKERS", "2")
READY_TIMEOUT = int(os.environ.get("API_READY_TIMEOUT", "90"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(url: str, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def main() -> int:
    port = _free_port()
    host = f"http://127.0.0.1:{port}"

    env = dict(os.environ)
    env.setdefault("ARGUS_FAST", "1")
    env["ARGUS_DB"] = os.path.join(tempfile.gettempdir(), f"argus_loadtest_{port}.db")
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")

    print(f"[run_locust] starting API: uvicorn on {host} (workers={WORKERS}, fast={env['ARGUS_FAST']})")
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "services.copilot.main:app",
         "--host", "127.0.0.1", "--port", str(port),
         "--workers", WORKERS, "--log-level", "warning"],
        cwd=ROOT, env=env, start_new_session=True)
    try:
        if not _wait_ready(f"{host}/readyz", READY_TIMEOUT):
            print(f"[run_locust] API not ready after {READY_TIMEOUT}s — aborting", file=sys.stderr)
            return 2
        print(f"[run_locust] API ready. Running locust: {USERS} users, spawn {SPAWN}/s, {RUNTIME}")
        locust = subprocess.run(
            [sys.executable, "-m", "locust", "-f", os.path.join(HERE, "locustfile.py"),
             "--headless", "-u", USERS, "-r", SPAWN, "-t", RUNTIME,
             "--host", host, "--only-summary"],
            cwd=ROOT, env=env)
        code = locust.returncode
        print(f"[run_locust] locust exit code: {code} ({'PASS' if code == 0 else 'FAIL'})")
        return code
    finally:
        try:
            os.killpg(os.getpgid(api.pid), signal.SIGTERM)
        except Exception:
            api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:
            try:
                os.killpg(os.getpgid(api.pid), signal.SIGKILL)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
