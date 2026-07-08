from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "codex-lb-deploy.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _base_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    live_compose = home / ".codex" / "codex-lb" / "docker-compose.yml"
    live_compose.parent.mkdir(parents=True)
    live_compose.write_text("services:\n  codex-lb:\n    image: codex-lb:active\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    curl_log = tmp_path / "curl.log"
    event_log = tmp_path / "events.log"

    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\\n' "$*" >> "$FAKE_DOCKER_LOG"
printf 'docker %s\\n' "$*" >> "$FAKE_EVENT_LOG"
if [[ "$*" == *" compose "* && "${FAKE_DOCKER_FAIL_COMPOSE:-0}" == "1" ]]; then
  printf 'compose failed\\n' >&2
  exit 42
fi
case "$*" in
  "buildx version"*) exit 0 ;;
  *" exec codex-lb python "*) printf '\\n'; exit 0 ;;
  *" logs --tail 200 codex-lb"*) printf '\\n'; exit 0 ;;
  *) exit 0 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\\n' "$*" >> "$FAKE_CURL_LOG"
printf 'curl %s\\n' "$*" >> "$FAKE_EVENT_LOG"
if [[ "$*" == *"/internal/drain/status"* ]]; then
  if [[ "${FAKE_DRAIN_STATUS_FAIL:-0}" == "1" ]]; then
    printf 'status unavailable\\n' >&2
    exit 22
  fi
  if [[ -n "${FAKE_DRAIN_STATUS_SEQUENCE:-}" ]]; then
    count=0
    if [[ -f "$FAKE_DRAIN_STATUS_COUNT_FILE" ]]; then
      count="$(cat "$FAKE_DRAIN_STATUS_COUNT_FILE")"
    fi
    count=$((count + 1))
    printf '%s' "$count" > "$FAKE_DRAIN_STATUS_COUNT_FILE"
    status="$(
      awk -v line="$count" 'NR == line { print; found = 1 } END { if (!found) exit 1 }' \
        "$FAKE_DRAIN_STATUS_SEQUENCE" || tail -n 1 "$FAKE_DRAIN_STATUS_SEQUENCE"
    )"
    printf '%s\\n' "$status"
    exit 0
  fi
  printf '%s\\n' "$FAKE_DRAIN_STATUS"
  exit 0
fi
if [[ "$*" == *"/internal/drain/start"* ]]; then
  printf '{"status":"ok","checks":{"draining":"ok"}}\\n'
  exit 0
fi
if [[ "$*" == *"/internal/drain/stop"* ]]; then
  printf '{"status":"ok","checks":{"draining":"stopped"}}\\n'
  exit 0
fi
if [[ "$*" == *"%{http_code}"* ]]; then
  printf '200'
  exit 0
fi
printf 'ok\\n'
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "PYTHON_BIN": sys.executable,
            "FAKE_DOCKER_LOG": str(docker_log),
            "FAKE_CURL_LOG": str(curl_log),
            "FAKE_EVENT_LOG": str(event_log),
            "FAKE_DRAIN_STATUS": (
                '{"status":"ok","checks":{"draining":"false","bridge_drain_active":"false","in_flight":"0"}}'
            ),
            "FAKE_DRAIN_STATUS_COUNT_FILE": str(tmp_path / "status-count.txt"),
            "FAKE_DRAIN_STATUS_SEQUENCE": "",
        }
    )
    return env


def test_deploy_refuses_to_build_or_recreate_when_live_proxy_has_in_flight_work(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["FAKE_DRAIN_STATUS"] = (
        '{"status":"ok","checks":{"draining":"false","bridge_drain_active":"false","in_flight":"2"}}'
    )

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    docker_log = (tmp_path / "docker.log").read_text() if (tmp_path / "docker.log").exists() else ""
    assert result.returncode != 0
    assert "in-flight" in result.stderr
    assert " build " not in docker_log
    assert " compose " not in docker_log


def test_deploy_fails_closed_when_live_drain_status_is_unreadable(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["FAKE_DRAIN_STATUS_FAIL"] = "1"

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    event_log = (tmp_path / "events.log").read_text()
    docker_log = (tmp_path / "docker.log").read_text() if (tmp_path / "docker.log").exists() else ""
    assert result.returncode != 0
    assert "unable to read live drain status" in result.stderr
    assert "/internal/drain/start" not in event_log
    assert " build " not in docker_log
    assert " compose " not in docker_log


def test_deploy_fails_closed_when_live_drain_status_is_malformed(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["FAKE_DRAIN_STATUS"] = "not-json"

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    docker_log = (tmp_path / "docker.log").read_text() if (tmp_path / "docker.log").exists() else ""
    assert result.returncode != 0
    assert "unable to parse live drain status" in result.stderr
    assert " build " not in docker_log
    assert " compose " not in docker_log


def test_deploy_starts_drain_and_waits_before_recreating_idle_container(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    event_log = (tmp_path / "events.log").read_text()
    drain_status_index = event_log.index("/internal/drain/status")
    drain_start_index = event_log.index("/internal/drain/start")
    compose_index = event_log.index(" compose ")
    assert result.returncode == 0, result.stderr
    assert drain_status_index < drain_start_index < compose_index


def test_deploy_stops_drain_after_post_drain_timeout(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    status_sequence = tmp_path / "status-sequence.txt"
    status_sequence.write_text(
        "\n".join(
            [
                '{"status":"ok","checks":{"draining":"false","bridge_drain_active":"false","in_flight":"0"}}',
                '{"status":"ok","checks":{"draining":"true","bridge_drain_active":"true","in_flight":"1"}}',
            ]
        )
        + "\n"
    )
    env["FAKE_DRAIN_STATUS_SEQUENCE"] = str(status_sequence)
    env["CODEX_LB_DEPLOY_DRAIN_TIMEOUT_SECONDS"] = "0"
    env["CODEX_LB_DEPLOY_DRAIN_POLL_SECONDS"] = "0"

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    event_log = (tmp_path / "events.log").read_text()
    assert result.returncode != 0
    assert "not recreating" in result.stderr
    assert "/internal/drain/start" in event_log
    assert "/internal/drain/stop" in event_log
    assert " compose " not in event_log
    assert event_log.index("/internal/drain/start") < event_log.index("/internal/drain/stop")


def test_deploy_stops_drain_after_force_recreate_failure(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["FAKE_DOCKER_FAIL_COMPOSE"] = "1"

    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    event_log = (tmp_path / "events.log").read_text()
    assert result.returncode != 0
    assert "/internal/drain/start" in event_log
    assert "/internal/drain/stop" in event_log
    assert event_log.index("/internal/drain/start") < event_log.index(" compose ")
    assert event_log.index(" compose ") < event_log.index("/internal/drain/stop")


def test_single_container_compose_files_pin_stable_bridge_instance_id() -> None:
    for compose_file in (REPO_ROOT / "docker-compose.yml", REPO_ROOT / "docker-compose.prod.yml"):
        text = compose_file.read_text()
        assert "CODEX_LB_HTTP_RESPONSES_SESSION_BRIDGE_INSTANCE_ID" in text
        assert "codex-lb-local" in text
