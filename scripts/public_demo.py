"""Run the isolated temporary public demo; Ctrl+C stops only child services."""
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    config = json.loads((ROOT / "var/public-demo.json").read_text())
    for port in (3000, 8000):
        with socket.socket() as check:
            if check.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is already in use. The demo may already be running.")
    processes, logs = [], []
    def start(args, name, env=None, cwd=ROOT):
        path = ROOT / "var" / ("demo-" + name + ".log")
        log = path.open("w")
        path.chmod(0o600)
        logs.append(log)
        process = subprocess.Popen(args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        processes.append(process)
        return process, path
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        tunnel, log_path = start(["cloudflared", "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:3000"], "tunnel")
        for _ in range(60):
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", log_path.read_text())
            if match:
                break
            if tunnel.poll() is not None:
                raise RuntimeError("Tunnel startup failed. See var/demo-tunnel.log.")
            time.sleep(1)
        else:
            raise RuntimeError("Tunnel did not provide a public URL within one minute.")
        origin = match.group(0)
        env = {**os.environ, "DATABASE_URL": config["database_url"], "APP_ORIGIN": origin,
               "DOCUMENT_ROOT": str(ROOT / "var/demo-documents"), "ENVIRONMENT": "production",
               "PYTHONPATH": str(ROOT / "backend")}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
        start([sys.executable, "-m", "uvicorn", "lubriflow.api:app", "--host", "127.0.0.1", "--port", "8000"], "api", env)
        start([sys.executable, "-m", "lubriflow.worker"], "worker", env)
        start(["npm", "run", "start", "--", "--hostname", "127.0.0.1"], "web", os.environ.copy(), ROOT / "frontend")
        config["origin"] = origin
        (ROOT / "var/public-demo.json").write_text(json.dumps(config, indent=2))
        print("Temporary demo starting: " + origin, flush=True)
        print("Private tester accounts: var/demo-access.json. Keep this terminal and Mac online. Ctrl+C stops sharing.", flush=True)
        while True:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A demo service stopped. Inspect var/demo-*.log before restarting.")
            time.sleep(2)
    except KeyboardInterrupt:
        print("Stopping public sharing and demo services.")
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
