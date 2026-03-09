import subprocess

import pytest

from poc.infra import ray_init


class DummyRay:
    def __init__(self):
        self.init_calls = []
        self._initialized = False
        self.failures = []

    def is_initialized(self):
        return self._initialized

    def init(self, **kwargs):
        self.init_calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        self._initialized = True

    def shutdown(self):
        self._initialized = False


def test_probe_existing_ray_cluster_found(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append((cmd, timeout))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(ray_init.subprocess, "run", fake_run)

    result = ray_init.probe_existing_ray_cluster()

    assert result == ray_init.RayClusterProbeResult(
        exists=True,
        reason="ok",
        returncode=0,
        stdout="ok",
        stderr="",
    )
    assert calls == [(["ray", "status"], ray_init._RAY_STATUS_TIMEOUT_SECONDS)]


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (FileNotFoundError(), "cli_missing"),
        (subprocess.TimeoutExpired(cmd=["ray", "status"], timeout=2), "timeout"),
        (RuntimeError("boom"), "exception:RuntimeError"),
    ],
)
def test_probe_existing_ray_cluster_handles_failures(monkeypatch, exc, reason):
    def fake_run(cmd, capture_output, text, timeout):
        raise exc

    monkeypatch.setattr(ray_init.subprocess, "run", fake_run)

    result = ray_init.probe_existing_ray_cluster()

    assert result.exists is False
    assert result.reason == reason


def test_probe_existing_ray_cluster_handles_nonzero_exit(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="cluster not found")

    monkeypatch.setattr(ray_init.subprocess, "run", fake_run)

    result = ray_init.probe_existing_ray_cluster()

    assert result == ray_init.RayClusterProbeResult(
        exists=False,
        reason="nonzero_exit",
        returncode=1,
        stdout="",
        stderr="cluster not found",
    )


def test_detect_existing_ray_cluster_delegates_to_probe(monkeypatch):
    monkeypatch.setattr(
        ray_init,
        "probe_existing_ray_cluster",
        lambda: ray_init.RayClusterProbeResult(exists=True, reason="ok"),
    )
    assert ray_init._detect_existing_ray_cluster() is True


def test_init_ray_connects_existing_cluster(monkeypatch):
    dummy_ray = DummyRay()
    monkeypatch.setattr(ray_init, "ray", dummy_ray)
    monkeypatch.setattr(ray_init, "_RAY_AVAILABLE", True)
    monkeypatch.setattr(
        ray_init,
        "probe_existing_ray_cluster",
        lambda: ray_init.RayClusterProbeResult(exists=True, reason="ok"),
    )
    restored = []
    monkeypatch.setattr(ray_init, "_restore_sigterm", lambda: restored.append(True))

    ok = ray_init.init_ray({"ray": {"enabled": True, "address": "auto", "namespace": "tower-eye"}})

    assert ok is True
    assert dummy_ray.init_calls == [{
        "address": "auto",
        "namespace": "tower-eye",
        "ignore_reinit_error": True,
    }]
    assert restored == [True]


def test_init_ray_falls_back_to_local_cluster_when_auto_connect_fails(monkeypatch, capsys):
    dummy_ray = DummyRay()
    dummy_ray.failures = [RuntimeError("auto connect boom")]
    monkeypatch.setattr(ray_init, "ray", dummy_ray)
    monkeypatch.setattr(ray_init, "_RAY_AVAILABLE", True)
    monkeypatch.setattr(
        ray_init,
        "probe_existing_ray_cluster",
        lambda: ray_init.RayClusterProbeResult(exists=True, reason="ok"),
    )
    restored = []
    monkeypatch.setattr(ray_init, "_restore_sigterm", lambda: restored.append(True))

    def fake_import_module(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(ray_init.importlib, "import_module", fake_import_module)

    ok = ray_init.init_ray({"ray": {
        "enabled": True,
        "address": "auto",
        "namespace": "tower-eye",
        "num_gpus": 2,
        "dashboard_port": 9999,
    }})

    assert ok is True
    assert dummy_ray.init_calls == [
        {
            "address": "auto",
            "namespace": "tower-eye",
            "ignore_reinit_error": True,
        },
        {
            "namespace": "tower-eye",
            "ignore_reinit_error": True,
            "num_gpus": 2,
            "include_dashboard": False,
        },
    ]
    assert restored == [True]
    captured = capsys.readouterr()
    assert "连接现有集群失败" in captured.out
    assert "回退启动新的本地 Ray 集群" in captured.out


def test_init_ray_reports_when_auto_connect_and_local_fallback_both_fail(monkeypatch, capsys):
    dummy_ray = DummyRay()
    dummy_ray.failures = [RuntimeError("auto connect boom"), RuntimeError("local start boom")]
    monkeypatch.setattr(ray_init, "ray", dummy_ray)
    monkeypatch.setattr(ray_init, "_RAY_AVAILABLE", True)
    monkeypatch.setattr(
        ray_init,
        "probe_existing_ray_cluster",
        lambda: ray_init.RayClusterProbeResult(exists=True, reason="ok"),
    )
    monkeypatch.setattr(ray_init, "_restore_sigterm", lambda: None)

    def fake_import_module(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(ray_init.importlib, "import_module", fake_import_module)

    ok = ray_init.init_ray({"ray": {
        "enabled": True,
        "address": "auto",
        "namespace": "tower-eye",
        "num_gpus": 2,
        "dashboard_port": 9999,
    }})

    assert ok is False
    assert dummy_ray.init_calls == [
        {
            "address": "auto",
            "namespace": "tower-eye",
            "ignore_reinit_error": True,
        },
        {
            "namespace": "tower-eye",
            "ignore_reinit_error": True,
            "num_gpus": 2,
            "include_dashboard": False,
        },
    ]
    captured = capsys.readouterr()
    assert "连接现有集群失败" in captured.out
    assert "本地集群启动失败" in captured.out
    assert "自动连接与本地回退均失败" in captured.out


def test_init_ray_starts_local_cluster_when_no_existing_cluster(monkeypatch):
    dummy_ray = DummyRay()
    monkeypatch.setattr(ray_init, "ray", dummy_ray)
    monkeypatch.setattr(ray_init, "_RAY_AVAILABLE", True)
    monkeypatch.setattr(
        ray_init,
        "probe_existing_ray_cluster",
        lambda: ray_init.RayClusterProbeResult(exists=False, reason="cli_missing"),
    )
    restored = []
    monkeypatch.setattr(ray_init, "_restore_sigterm", lambda: restored.append(True))

    def fake_import_module(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(ray_init.importlib, "import_module", fake_import_module)

    ok = ray_init.init_ray({"ray": {
        "enabled": True,
        "address": "auto",
        "namespace": "tower-eye",
        "num_gpus": 2,
        "dashboard_port": 9999,
    }})

    assert ok is True
    assert dummy_ray.init_calls == [{
        "namespace": "tower-eye",
        "ignore_reinit_error": True,
        "num_gpus": 2,
        "include_dashboard": False,
    }]
    assert restored == [True]


def test_init_ray_starts_local_cluster_with_dashboard_when_module_available(monkeypatch):
    dummy_ray = DummyRay()
    monkeypatch.setattr(ray_init, "ray", dummy_ray)
    monkeypatch.setattr(ray_init, "_RAY_AVAILABLE", True)
    monkeypatch.setattr(
        ray_init,
        "probe_existing_ray_cluster",
        lambda: ray_init.RayClusterProbeResult(exists=False, reason="cli_missing"),
    )
    restored = []
    monkeypatch.setattr(ray_init, "_restore_sigterm", lambda: restored.append(True))

    imported = []

    def fake_import_module(name):
        imported.append(name)
        assert name == "ray.dashboard"
        return object()

    monkeypatch.setattr(ray_init.importlib, "import_module", fake_import_module)

    ok = ray_init.init_ray({"ray": {
        "enabled": True,
        "address": "auto",
        "namespace": "tower-eye",
        "num_gpus": 2,
        "dashboard_port": 9999,
    }})

    assert ok is True
    assert imported == ["ray.dashboard"]
    assert dummy_ray.init_calls == [{
        "namespace": "tower-eye",
        "ignore_reinit_error": True,
        "num_gpus": 2,
        "include_dashboard": True,
        "dashboard_port": 9999,
    }]
    assert restored == [True]
