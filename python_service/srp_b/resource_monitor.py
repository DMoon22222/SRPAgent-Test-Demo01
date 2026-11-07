"""Read-only local Engine stats with bounded helper lifetime and explicit scope."""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import quote, urlsplit

MAX_BODY = 1024 * 1024
MAX_SAMPLES = 64
QUERY_TIMEOUT = 1.0
SAMPLE_INTERVAL = 0.2


def local_endpoint():
    if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
        endpoint = os.environ["DOCKER_HOST"]
    else:
        result = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"],
            capture_output=True, text=True, timeout=QUERY_TIMEOUT, check=False,
        )
        if result.returncode:
            raise OSError("LOCAL_DOCKER_CONTEXT_UNAVAILABLE")
        endpoint = json.loads(result.stdout)
    if not isinstance(endpoint, str) or len(endpoint) > 512:
        raise ValueError("UNSUPPORTED_STATS_ENDPOINT")
    if endpoint.startswith("npipe:////./pipe/") and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", endpoint.rsplit("/", 1)[-1]):
        return endpoint
    parsed = urlsplit(endpoint)
    if parsed.scheme == "unix" and not parsed.netloc and parsed.path.startswith("/") and not parsed.query and not parsed.fragment:
        return endpoint
    raise ValueError("ONLY_LOCAL_PIPE_OR_UNIX_STATS_SUPPORTED")


class _PipeSocket:
    def __init__(self, stream):
        self.stream = stream

    def makefile(self, *args, **kwargs):
        return self.stream


def _read_local_stats(endpoint, name):
    if not re.fullmatch(r"srp-b-[A-Za-z0-9_.-]{1,160}", name):
        raise ValueError("INVALID_CONTAINER_NAME")
    path = "/containers/" + quote(name, safe="") + "/stats?stream=false&one-shot=true"
    request = f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode("ascii")
    with ExitStack() as cleanup:
        if endpoint.startswith("npipe:////./pipe/"):
            leaf = endpoint.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", leaf):
                raise ValueError("INVALID_PIPE")
            stream = cleanup.enter_context(open("\\\\.\\pipe\\" + leaf, "r+b", buffering=0))
            stream.write(request)
            connection = _PipeSocket(stream)
        else:
            parsed = urlsplit(endpoint)
            if parsed.scheme != "unix" or parsed.netloc or not parsed.path.startswith("/"):
                raise ValueError("INVALID_SOCKET")
            connection = cleanup.enter_context(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
            connection.settimeout(QUERY_TIMEOUT)
            connection.connect(parsed.path)
            connection.sendall(request)
        response = http.client.HTTPResponse(connection)
        cleanup.callback(response.close)
        response.begin()
        body = response.read(MAX_BODY + 1)
        if response.status != 200 or len(body) > MAX_BODY:
            raise ValueError("STATS_RESPONSE_UNAVAILABLE")
        data = json.loads(body)
        return {key: data.get(key) for key in ("read", "cpu_stats", "memory_stats")}


class LocalStatsClient:
    """An isolated stdlib helper bounds blocking named-pipe I/O on Windows."""

    def __init__(self):
        self.endpoint = local_endpoint()
        self.active = None
        self.lock = threading.Lock()

    def __call__(self, name):
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--sample", self.endpoint, name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        with self.lock:
            self.active = process
        try:
            stdout, _ = process.communicate(timeout=QUERY_TIMEOUT)
            if process.returncode or len(stdout) > MAX_BODY:
                raise OSError("STATS_HELPER_UNAVAILABLE")
            result = json.loads(stdout)
            if not result.get("available"):
                raise OSError("STATS_NOT_AVAILABLE")
            return result["data"]
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=QUERY_TIMEOUT)
            raise OSError("STATS_HELPER_TIMEOUT") from None
        finally:
            with self.lock:
                self.active = None
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=QUERY_TIMEOUT)

    def cancel(self):
        with self.lock:
            process = self.active
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass


def _number(value):
    return value if type(value) is int and value >= 0 else None


class ResourceMonitor:
    def __init__(self, name, policy, *, fetch=None, interval=SAMPLE_INTERVAL, clock=time.monotonic):
        self.name, self.policy, self.clock = name, policy, clock
        self.fetch = fetch
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None
        self.samples = []
        self.sample_count = 0
        self.maxima = {}
        self.errors = 0
        self.unavailable_reason = None
        self.started = self.clock()

    def start(self):
        self.thread = threading.Thread(target=self._loop, name="b-resource-monitor-" + self.name[-12:], daemon=True)
        self.thread.start()

    def _loop(self):
        if self.fetch is None:
            try:
                self.fetch = LocalStatsClient()
            except (OSError, ValueError, TypeError, subprocess.SubprocessError):
                self.unavailable_reason = "LOCAL_ENGINE_STATS_UNAVAILABLE"
                return
        while not self.stop_event.is_set():
            began = self.clock()
            try:
                data = self.fetch(self.name)
                cpu = data.get("cpu_stats") or {}
                memory = data.get("memory_stats") or {}
                if data.get("read") and not data["read"].startswith("0001"):
                    snapshot = {
                        "elapsed_ms": round((self.clock() - self.started) * 1000, 3),
                        "daemon_read_at": data["read"],
                        "cpu_total_ns": _number((cpu.get("cpu_usage") or {}).get("total_usage")),
                        "memory_usage_bytes": _number(memory.get("usage")),
                        "kernel_memory_max_bytes": _number(memory.get("max_usage")),
                        "observed_memory_limit_bytes": _number(memory.get("limit")),
                        "cpu_throttled_periods": _number((cpu.get("throttling_data") or {}).get("throttled_periods")),
                        "cpu_throttled_time_ns": _number((cpu.get("throttling_data") or {}).get("throttled_time")),
                    }
                    if snapshot["cpu_total_ns"] is not None or snapshot["memory_usage_bytes"] is not None:
                        self.sample_count += 1
                        for key, value in snapshot.items():
                            if key not in {"elapsed_ms", "daemon_read_at"} and value is not None:
                                self.maxima[key] = max(self.maxima.get(key, value), value)
                        self.samples.append(snapshot)
                        del self.samples[:-MAX_SAMPLES]
            except Exception:  # noqa: BLE001 -- optional observations must not escape the monitor thread.
                self.errors += 1
            self.stop_event.wait(max(0.0, self.interval - (self.clock() - began)))

    def stop(self):
        self.stop_event.set()
        try:
            if hasattr(self.fetch, "cancel"):
                self.fetch.cancel()
        except Exception:  # noqa: BLE001 -- still join the thread if cancellation itself fails.
            self.errors += 1
        finally:
            if self.thread is not None:
                self.thread.join(timeout=2 * QUERY_TIMEOUT + 0.5)
        return self.result()

    def result(self):
        def maximum(key):
            return self.maxima.get(key)
        cpu, memory, kernel_max = maximum("cpu_total_ns"), maximum("memory_usage_bytes"), maximum("kernel_memory_max_bytes")
        if not kernel_max:
            kernel_max = None
        intervals = [b["elapsed_ms"] - a["elapsed_ms"] for a, b in zip(self.samples, self.samples[1:], strict=False)]
        return {
            "version": "docker-resource-v1", "source": "local Docker Engine stats; no process injected into target",
            "sample_count": self.sample_count, "samples": list(self.samples), "sampling_errors": self.errors,
            "retained_sample_count": len(self.samples), "sample_retention_limit": MAX_SAMPLES,
            "retention_scope": "Last 64 samples; cumulative maxima retain all successful samples until stop",
            "sample_interval_requested_ms": self.interval * 1000,
            "sample_intervals_observed_ms": intervals,
            "cpu_time_ms": cpu / 1000000 if cpu is not None else None,
            "cpu_scope": "Last observed cumulative container CPU counter; may omit unsampled execution tail",
            "peak_memory_bytes": max(memory or 0, kernel_max or 0) if memory is not None or kernel_max is not None else None,
            "memory_method": "observed_kernel_max_counter" if kernel_max is not None else "maximum_sampled_usage_including_cache",
            "memory_scope": "Observed window, not guaranteed full-lifetime peak; includes container accounting/cache",
            "observed_memory_limit_bytes": maximum("observed_memory_limit_bytes"),
            "memory_limit_bytes": self.policy["memory_mb"] * 1024 * 1024,
            "limits_source": "ExecutionPolicy applied by unchanged Docker create arguments",
            "cpu_limit": self.policy["cpu_limit"],
            "cpu_throttled": (maximum("cpu_throttled_periods") > 0) if maximum("cpu_throttled_periods") is not None else None,
            "monitor_thread_cleanup_confirmed": self.thread is None or not self.thread.is_alive(),
            "unavailable_reason": self.unavailable_reason or ("NO_VALID_SAMPLE_IN_OBSERVED_WINDOW" if not self.samples else None),
            "measurement_status": "estimated" if self.samples else "unknown",
        }


def _main():
    if len(sys.argv) != 4 or sys.argv[1] != "--sample":
        raise SystemExit("Internal stats helper only")
    try:
        result = {"available": True, "data": _read_local_stats(sys.argv[2], sys.argv[3])}
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        result = {"available": False}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    _main()
