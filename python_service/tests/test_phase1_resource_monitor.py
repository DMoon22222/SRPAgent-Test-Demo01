"""Resource observations are bounded, explicit and independent of outcomes."""

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from srp_b.module import EXECUTE
from srp_b.resource_monitor import (
    MAX_SAMPLES,
    LocalStatsClient,
    ResourceMonitor,
    local_endpoint,
)
from srp_b.samples import request
from srp_b.sandbox import Command, DockerRunner


def policy():
    return request(EXECUTE)["payload"]["execution_policy"]


def sample(cpu=10000000, memory=12345, **changes):
    result = {"read": "2026-11-07T07:00:00Z", "cpu_stats": {"cpu_usage": {"total_usage": cpu},
              "throttling_data": {"throttled_periods": 2}}, "memory_stats": {"usage": memory, "limit": 268435456}}
    result.update(changes)
    return result


def wait_samples(monitor, count=1):
    end = time.monotonic() + 2
    while len(monitor.samples) < count and time.monotonic() < end:
        time.sleep(0.002)
    assert len(monitor.samples) >= count


def test_real_counter_units_and_sampled_maximum():
    values = iter([sample(10000000, 12345), sample(20000000, 23456), sample(15000000, 20000)])
    monitor = ResourceMonitor("srp-b-unit", policy(), fetch=lambda _: next(values, sample(20000000, 23456)), interval=0.005)
    monitor.start()
    wait_samples(monitor, 3)
    result = monitor.stop()
    assert result["cpu_time_ms"] == 20 and result["peak_memory_bytes"] == 23456
    assert result["memory_method"] == "maximum_sampled_usage_including_cache"
    assert result["cpu_throttled"] is True and result["monitor_thread_cleanup_confirmed"]
    assert result["sample_intervals_observed_ms"]


def test_kernel_max_and_sparse_metric_availability():
    monitor = ResourceMonitor("srp-b-unit", policy(), fetch=lambda _: sample(None, 100, memory_stats={"usage": 100, "max_usage": 200}), interval=0.005)
    monitor.start()
    wait_samples(monitor)
    result = monitor.stop()
    assert result["cpu_time_ms"] is None and result["peak_memory_bytes"] == 200
    assert result["memory_method"] == "observed_kernel_max_counter"


def test_missing_or_negative_metrics_are_not_filled_with_zero():
    monitor = ResourceMonitor("srp-b-unit", policy(), fetch=lambda _: sample(-1, -1), interval=0.005)
    monitor.start()
    time.sleep(0.02)
    result = monitor.stop()
    assert result["cpu_time_ms"] is result["peak_memory_bytes"] is None
    assert result["sample_count"] == 0 and result["measurement_status"] == "unknown"


def test_explicit_observed_zero_differs_from_unavailable():
    monitor = ResourceMonitor("srp-b-unit", policy(), fetch=lambda _: sample(0, 0), interval=0.005)
    monitor.start()
    wait_samples(monitor)
    result = monitor.stop()
    assert result["cpu_time_ms"] == result["peak_memory_bytes"] == 0
    assert result["measurement_status"] == "estimated"


def test_observer_exception_is_contained_and_thread_stops():
    def failed(_):
        raise RuntimeError("synthetic observer failure")
    monitor = ResourceMonitor("srp-b-unit", policy(), fetch=failed, interval=0.005)
    monitor.start()
    time.sleep(0.02)
    result = monitor.stop()
    assert result["sampling_errors"] > 0 and result["monitor_thread_cleanup_confirmed"]
    assert result["cpu_time_ms"] is None


def test_sample_storage_has_a_fixed_upper_bound():
    called = 0
    def fetch(_):
        nonlocal called
        called += 1
        return sample(cpu=called * 1000000, memory=999999 if called == 1 else called)
    monitor = ResourceMonitor("srp-b-unit", policy(), fetch=fetch, interval=0.001)
    monitor.start()
    wait_samples(monitor, MAX_SAMPLES)
    end = time.monotonic() + 2
    while monitor.sample_count <= MAX_SAMPLES + 2 and time.monotonic() < end:
        time.sleep(0.002)
    result = monitor.stop()
    assert result["sample_count"] > MAX_SAMPLES
    assert result["retained_sample_count"] == MAX_SAMPLES
    assert result["cpu_time_ms"] > MAX_SAMPLES and result["peak_memory_bytes"] == 999999


def test_malformed_stats_are_unavailable_without_thread_error():
    monitor = ResourceMonitor("srp-b-unit", policy(), fetch=lambda _: {"read": 123}, interval=0.005)
    monitor.start()
    time.sleep(0.02)
    result = monitor.stop()
    assert result["sampling_errors"] > 0 and result["monitor_thread_cleanup_confirmed"]
    assert result["cpu_time_ms"] is None


def test_cancellable_sampler_does_not_leave_an_auxiliary_thread():
    class Blocking:
        def __init__(self):
            self.entered, self.release = threading.Event(), threading.Event()

        def __call__(self, _):
            self.entered.set()
            self.release.wait(1)
            return sample()

        def cancel(self):
            self.release.set()
    fetch = Blocking()
    monitor = ResourceMonitor("srp-b-unit", policy(), fetch=fetch)
    monitor.start()
    assert fetch.entered.wait(1)
    assert monitor.stop()["monitor_thread_cleanup_confirmed"]


def test_nonlocal_endpoint_is_unavailable_without_opening_network(monkeypatch):
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:2375")
    with pytest.raises(ValueError, match="ONLY_LOCAL"):
        local_endpoint()


def test_helper_timeout_kills_process_and_clears_tracking(monkeypatch):
    import srp_b.resource_monitor as module

    class Process:
        returncode = None
        killed = 0
        calls = 0

        def communicate(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("helper", timeout)
            self.returncode = -1
            return b"", b""

        def kill(self):
            self.killed += 1

        def poll(self):
            return self.returncode
    process = Process()
    monkeypatch.setattr(module, "local_endpoint", lambda: "npipe:////./pipe/docker_engine")
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: process)
    client = LocalStatsClient()
    with pytest.raises(OSError, match="TIMEOUT"):
        client("srp-b-unit")
    assert process.killed == 1 and client.active is None


class SyntheticDocker:
    """Native runner orchestration with no physical command or target execution."""

    def __init__(self):
        self.workspace = None
        self.created_args = []
        self.cleaned = False

    def __call__(self, args, timeout, **kwargs):
        if args[:3] == ["docker", "image", "inspect"]:
            return Command(0, ("sha256:" + "a" * 64).encode(), b"")
        if args[:2] == ["docker", "create"]:
            self.created_args.append(args)
            for part in args:
                if part.startswith("type=bind,source=") and part.endswith("target=/workspace,readonly"):
                    self.workspace = Path(part.split("source=", 1)[1].split(",target=", 1)[0])
            return Command(0, b"container", b"")
        if args[:2] == ["docker", "start"]:
            if args[-1].endswith("-probe"):
                return Command(0, json.dumps({"runtime": {"name": "python", "version": "3.11.5"}, "packages": [{"name": "pytest", "version": "8.3.5", "source": "observed"}]}).encode(), b"")
            (self.workspace / "tmp/b-junit.xml").write_bytes(b'<testsuite><testcase name="test_add"/></testsuite>')
            return Command(0, b"one test passed", b"")
        if args[:2] == ["docker", "inspect"]:
            return Command(0, json.dumps({"StartedAt": "2026-11-07", "ExitCode": 0, "Running": False, "OOMKilled": False}).encode(), b"")
        if args[:2] == ["docker", "rm"]:
            self.cleaned = True
            return Command(0, b"removed", b"")
        raise AssertionError(args)


@pytest.mark.parametrize("failure", ["start", "stop"])
def test_observer_failure_does_not_change_native_execution_result(failure):
    cleanup_seen_by_monitor = []
    class BrokenMonitor:
        def __init__(self, *args):
            pass

        def start(self):
            if failure == "start":
                raise RuntimeError("observer start")

        def stop(self):
            cleanup_seen_by_monitor.append(command.cleaned)
            raise RuntimeError("observer stop")
    command = SyntheticDocker()
    observed = DockerRunner("fixed-image", command=command, monitor_factory=BrokenMonitor).execute(
        request(EXECUTE)["payload"], timeout_seconds=10, execution_id="unit-monitor",
    )
    assert observed["execution_status"] == "completed" and observed["test_outcome"] == "passed"
    assert observed["isolation_guarantees"]["container_cleanup_confirmed"]
    assert observed["resource_usage"]["cpu_time_ms"] is None
    assert cleanup_seen_by_monitor == [True]
    for args in command.created_args:
        assert args[args.index("--network") + 1] == "none" and "--read-only" in args
        assert "--cap-drop" in args and "--privileged" not in args
