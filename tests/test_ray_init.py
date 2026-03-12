"""Tests for Ray bootstrap/connect target resolution."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.infra.ray_init import resolve_ray_target


def test_auto_uses_env_address():
    config = {"ray": {"enabled": True, "address": "auto"}}
    target, source = resolve_ray_target(
        config,
        mode="connect_only",
        env_address="127.0.0.1:6379",
    )
    assert target == "127.0.0.1:6379"
    assert source == "env.bootstrap"


def test_auto_uses_bootstrap_file_address():
    config = {"ray": {"enabled": True, "address": "auto"}}
    target, source = resolve_ray_target(
        config,
        mode="connect_only",
        bootstrap_address="127.0.0.1:6380",
    )
    assert target == "127.0.0.1:6380"
    assert source == "bootstrap.file"


def test_auto_connect_only_requires_bootstrap_address():
    config = {"ray": {"enabled": True, "address": "auto"}}
    target, source = resolve_ray_target(config, mode="connect_only")
    assert target is None
    assert source == "connect_only.missing_address"


def test_auto_bootstrap_falls_back_to_local():
    config = {"ray": {"enabled": True, "address": "auto"}}
    target, source = resolve_ray_target(config, mode="bootstrap")
    assert target == "local"
    assert source == "bootstrap.local"


def test_explicit_address_wins():
    config = {"ray": {"enabled": True, "address": "10.0.0.8:9000"}}
    target, source = resolve_ray_target(config, mode="connect_only")
    assert target == "10.0.0.8:9000"
    assert source == "config.address"


def test_explicit_local_wins():
    config = {"ray": {"enabled": True, "address": "local"}}
    target, source = resolve_ray_target(config, mode="connect_only")
    assert target == "local"
    assert source == "config.local"


if __name__ == "__main__":
    test_auto_uses_env_address()
    test_auto_uses_bootstrap_file_address()
    test_auto_connect_only_requires_bootstrap_address()
    test_auto_bootstrap_falls_back_to_local()
    test_explicit_address_wins()
    test_explicit_local_wins()
    print("=== ALL TESTS PASSED ===")
