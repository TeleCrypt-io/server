#!/usr/bin/env python3
"""Tests the exact image manifest and release behavior used by Server State."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import yaml
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent))
import validate  # noqa: E402


CONTAINER_HELPER = Path(__file__).parent / "container-helpers.sh"
RELEASE_HELPER = Path(__file__).parent / "release-helpers.sh"
WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "validate.yml"
TEST_VALUES = {
    "CADDY_IMAGE": "docker.io/caddy:2.11.4-alpine",
    "SYNAPSE_IMAGE": "ghcr.io/telecrypt-io/telecrypt-synapse:1.159-tc25",
    "MAS_IMAGE": "ghcr.io/element-hq/matrix-authentication-service:1.23.0",
    "CONTROLPLANE_IMAGE": "ghcr.io/telecrypt-io/controlplane:0.5.33",
    "CASHIER_IMAGE": "ghcr.io/telecrypt-io/telecrypt-cashier:0.4.28",
    "LK_JWT_IMAGE": "ghcr.io/element-hq/lk-jwt-service:0.7.0",
}
os.environ.update(TEST_VALUES)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def workflow_run(job_name: str, step_id: str) -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in workflow["jobs"][job_name]["steps"]:
        if step.get("id") == step_id:
            return step["run"]
    raise AssertionError((job_name, step_id))


class ManifestTests(unittest.TestCase):

    def test_manifest_has_exactly_six_versioned_images(self) -> None:
        values = validate.load_manifest()
        self.assertEqual(set(values), set(validate.IMAGE_KEYS))
        self.assertEqual(len(set(values.values())), len(validate.IMAGE_KEYS))
        with self.assertRaises(AssertionError):
            validate.parse_manifest([*(f"{key}={value}" for key, value in values.items()), "EXTRA=x:1"])

    def test_image_platform_and_provenance_are_bound(self) -> None:
        controlplane_version = validate.load_manifest()["CONTROLPLANE_IMAGE"].rsplit(":", 1)[1]
        validate.validate_image_platform(
            {"Os": "linux", "Architecture": "amd64", "Digest": "sha256:" + "a" * 64},
            {"os": "linux", "architecture": "amd64"},
        )
        labels = {
            "org.opencontainers.image.source": "https://github.com/TeleCrypt-io/synapse-server",
            "org.opencontainers.image.revision": "a" * 40,
            "org.opencontainers.image.version": "1.159-tc3",
            "org.opencontainers.image.base.name": "ghcr.io/element-hq/synapse",
            "org.opencontainers.image.base.version": "1.159.0",
            "org.telecrypt.controlplane.release": controlplane_version,
            "org.telecrypt.s3-provider.version": "1.7.0",
            "org.telecrypt.controlplane.wheel.sha256": "a" * 64,
            "org.telecrypt.s3-provider.fork.archive.sha256": "b" * 64,
        }
        validate.validate_synapse_provenance(labels, dict(labels), "1.159-tc3")
        with self.assertRaises(AssertionError):
            validate.validate_image_platform(
                {"Os": "linux", "Architecture": "arm64"},
                {"os": "linux", "architecture": "amd64"},
            )
        changed = dict(labels)
        changed["org.telecrypt.controlplane.release"] = "latest"
        with self.assertRaises(AssertionError):
            validate.validate_synapse_provenance(labels, changed, "1.159-tc3")

    def test_published_image_config_allows_omitted_null_fields_only(self) -> None:
        values = validate.load_manifest()
        values["CONTROLPLANE_IMAGE"] = "ghcr.io/telecrypt-io/controlplane:0.5.18"
        digest = "sha256:" + "a" * 64
        synapse_labels = {
            "org.opencontainers.image.source": "https://github.com/TeleCrypt-io/synapse-server",
            "org.opencontainers.image.revision": "a" * 40,
            "org.opencontainers.image.version": values["SYNAPSE_IMAGE"].rsplit(":", 1)[1],
            "org.opencontainers.image.base.name": "ghcr.io/element-hq/synapse",
            "org.opencontainers.image.base.version": "1.159.0",
            "org.telecrypt.controlplane.release": "0.5.17",
            "org.telecrypt.s3-provider.version": "1.7.0",
            "org.telecrypt.controlplane.wheel.sha256": "b" * 64,
            "org.telecrypt.s3-provider.fork.archive.sha256": "c" * 64,
        }
        product_labels = {
            key: {
                "org.opencontainers.image.source": f"https://github.com/TeleCrypt-io/{'control-plane' if key == 'CONTROLPLANE_IMAGE' else 'cashier'}",
                "org.opencontainers.image.version": values[key].rsplit(":", 1)[1],
                "org.opencontainers.image.revision": "d" * 40,
                "io.telecrypt.config-contract": "1",
            }
            for key in ("CONTROLPLANE_IMAGE", "CASHIER_IMAGE")
        }
        base_configs = {
            "CADDY_IMAGE": {"Cmd": ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]},
            "SYNAPSE_IMAGE": {"Labels": synapse_labels},
            "MAS_IMAGE": {"Entrypoint": ["/usr/local/bin/mas-cli"]},
            "LK_JWT_IMAGE": {"Cmd": ["/lk-jwt-service"]},
            "CONTROLPLANE_IMAGE": {"Cmd": ["/registration"], "Labels": product_labels["CONTROLPLANE_IMAGE"], "User": "991:991"},
            "CASHIER_IMAGE": {"Entrypoint": ["/cashier"], "Labels": product_labels["CASHIER_IMAGE"], "User": "991:991"},
        }

        def write_fixture(directory: Path, mutate=None) -> None:
            configs = {key: dict(config) for key, config in base_configs.items()}
            if mutate is not None:
                mutate(configs)
            for key, image in values.items():
                name = validate.image_reference_filename(image)
                labels = synapse_labels if key == "SYNAPSE_IMAGE" else product_labels.get(key, {})
                config_document = {"os": "linux", "architecture": "amd64", "config": configs[key]}
                metadata = {
                    "Name": image.rsplit(":", 1)[0],
                    "Digest": digest,
                    "Os": "linux",
                    "Architecture": "amd64",
                }
                (directory / f"{name}.labels").write_text(json.dumps(labels), encoding="utf-8")
                (directory / f"{name}.config").write_text(json.dumps(config_document), encoding="utf-8")
                (directory / f"{name}.metadata").write_text(json.dumps(metadata), encoding="utf-8")

        with mock.patch.object(validate, "load_manifest", return_value=values), tempfile.TemporaryDirectory(delete=False, prefix="server-state-image-config-") as directory:
            root = Path(directory)
            valid = root / "valid"
            valid.mkdir()
            write_fixture(valid)
            validate.validate_published_images(valid)

            mutations = {
                "missing-required-command": lambda configs: configs["CADDY_IMAGE"].pop("Cmd"),
                "wrong-required-command": lambda configs: configs["CADDY_IMAGE"].update(Cmd=["unexpected"]),
                "missing-required-entrypoint": lambda configs: configs["MAS_IMAGE"].pop("Entrypoint"),
                "wrong-livekit-command": lambda configs: configs["LK_JWT_IMAGE"].update(Cmd=["unexpected"]),
                "wrong-required-entrypoint": lambda configs: configs["MAS_IMAGE"].update(Entrypoint=["unexpected"]),
                "invalid-wheel-release": lambda configs: configs["SYNAPSE_IMAGE"].update(Labels={**synapse_labels, "org.telecrypt.controlplane.release": "latest"}),
                "mismatched-wheel-release": lambda configs: configs["SYNAPSE_IMAGE"].update(Labels={**synapse_labels, "org.telecrypt.controlplane.release": "0.5.16"}),
                "invalid-wheel-digest": lambda configs: configs["SYNAPSE_IMAGE"].update(Labels={**synapse_labels, "org.telecrypt.controlplane.wheel.sha256": "invalid"}),
                "mismatched-wheel-digest": lambda configs: configs["SYNAPSE_IMAGE"].update(Labels={**synapse_labels, "org.telecrypt.controlplane.wheel.sha256": "d" * 64}),
                "wrong-synapse-source": lambda configs: configs["SYNAPSE_IMAGE"].update(Labels={**synapse_labels, "org.opencontainers.image.source": "https://github.com/other/synapse"}),
            }
            for name, mutation in mutations.items():
                with self.subTest(name=name):
                    invalid = root / name
                    invalid.mkdir()
                    write_fixture(invalid, mutation)
                    with self.assertRaises(AssertionError):
                        validate.validate_published_images(invalid)


class ConfigurationRenderingTests(unittest.TestCase):

    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]
        self.pillar = {
            "telecrypt": {
                "server_name": "stage.example.invalid",
                "admin_client_id": "01J00000000000000000000000",
                "mas_rust_log": "info,mas=debug",
                "mas_rate_limiting": {
                    "login_per_ip_burst": 100000,
                    "login_per_ip_per_second": 1000.0,
                    "login_per_account_burst": 100000,
                    "login_per_account_per_second": 1000.0,
                    "registration_burst": 100000,
                    "registration_per_second": 1000.0,
                },
                "synapse_rate_limiting": {
                    "message_per_second": 1000,
                    "message_burst": 1000,
                    "room_creation_per_second": 1000,
                    "room_creation_burst": 1000,
                },
                "synapse_http_log_level": "DEBUG",
                "synapse_http_client_log_level": "DEBUG",
            }
        }
        self.environment = Environment(loader=FileSystemLoader(str(self.root)))

    def render(self, name: str) -> dict:
        return yaml.safe_load(self.environment.get_template(name).render(pillar=self.pillar))

    def test_private_profile_values_render_without_hostname_selection(self) -> None:
        mas = self.render("matrix/mas.runtime.yaml.j2")
        synapse = self.render("matrix/synapse.runtime.yaml.j2")
        log_config = self.render("matrix/synapse.log.config.j2")
        self.assertEqual(mas["rate_limiting"]["login"]["per_ip"]["burst"], 100000)
        self.assertEqual(mas["rate_limiting"]["registration"]["per_second"], 1000.0)
        self.assertEqual(synapse["rc_message"]["per_second"], 1000)
        self.assertEqual(log_config["loggers"]["synapse.http.server"]["level"], "DEBUG")
        for path in ("matrix/mas.runtime.yaml.j2", "matrix/synapse.runtime.yaml.j2", "matrix/synapse.log.config.j2"):
            self.assertNotIn("stage.telecrypt.io", (self.root / path).read_text(encoding="utf-8"))

    def test_caddy_routes_remain_environment_derived(self) -> None:
        caddy = (self.root / "Caddyfile").read_text(encoding="utf-8")
        for route in ("/auth", "/_matrix/client", "/livekit/jwt", "/plan", "/internal"):
            self.assertIn(route, caddy)
        self.assertIn("import server.{$SERVER_NAME}", caddy)


class ReleaseWorkflowGitTests(unittest.TestCase):

    def test_dispatch_inputs_and_candidate_tag_are_unique(self) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(set(triggers["workflow_dispatch"]["inputs"]), {"synapse_tag", "controlplane_tag", "cashier_tag"})
        self.assertEqual(workflow["jobs"]["assemble"]["if"], "github.event_name == 'workflow_dispatch'")
        commit = "a" * 40
        first = f"server-state-{commit[:8]}-41"
        second = f"server-state-{commit[:8]}-42"
        self.assertRegex(first, validate.SERVER_STATE_TAG)
        self.assertRegex(second, validate.SERVER_STATE_TAG)
        self.assertNotEqual(first, second)

    def test_selected_inputs_accept_release_tags_without_semver_policy(self) -> None:
        values = dict(TEST_VALUES)
        values["SYNAPSE_IMAGE"] = "ghcr.io/telecrypt-io/telecrypt-synapse:release-candidate"
        values["CASHIER_IMAGE"] = "ghcr.io/telecrypt-io/telecrypt-cashier:2026.09-preview"
        self.assertEqual(validate.load_manifest(values), values)
        values["CASHIER_IMAGE"] = "docker.io/other:release"
        with self.assertRaises(AssertionError):
            validate.load_manifest(values)


class ReleaseCaptureTests(unittest.TestCase):

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(delete=False, prefix="server-state-release-capture-")
        self.root = Path(self.directory.name)
        self.output = self.root / "output"
        self.stderr_file = self.root / "stderr"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def run_capture(self, command: str, *, binary: bool = False, timeout_seconds: int = 5, text: bool = True):
        helper = shlex.quote(str(RELEASE_HELPER))
        mode = "--binary-output " if binary else ""
        shell = (
            f"source {helper}; capture_command {mode}{shlex.quote(str(self.output))} "
            f"{shlex.quote(str(self.stderr_file))} {timeout_seconds} {command}"
        )
        return subprocess.run(
            ["/bin/bash", "-euo", "pipefail", "-c", shell],
            cwd=self.root,
            capture_output=True,
            text=text,
            timeout=10,
            check=False,
        )

    def test_success_keeps_stdout_for_parsing_and_reports_stderr(self) -> None:
        result = self.run_capture("/usr/bin/python3 -c 'import sys; print(\"payload\"); print(\"warning\", file=sys.stderr)'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "payload\n")
        self.assertEqual(self.stderr_file.read_text(encoding="utf-8"), "warning\n")
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "warning\n")

    def test_failure_replays_complete_text_output_and_preserves_status(self) -> None:
        result = self.run_capture("/usr/bin/python3 -c 'import sys; print(\"partial\"); print(\"failure\", file=sys.stderr); sys.exit(23)'")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "partial\n")
        self.assertEqual(self.stderr_file.read_text(encoding="utf-8"), "failure\n")
        self.assertIn("partial\nfailure\n", result.stderr)

    def test_binary_failure_does_not_replay_payload_to_runner_log(self) -> None:
        result = self.run_capture(
            "/usr/bin/python3 -c 'import sys; sys.stdout.buffer.write(b\"\\x00payload\"); print(\"failure\", file=sys.stderr); sys.exit(9)'",
            binary=True,
            text=False,
        )
        self.assertEqual(result.returncode, 9)
        self.assertEqual(self.output.read_bytes(), b"\x00payload")
        self.assertNotIn(b"payload", result.stderr)
        self.assertIn(b"failure", result.stderr)

    def test_timeout_replays_partial_diagnostics_and_returns_timeout_status(self) -> None:
        result = self.run_capture("/bin/bash -c 'printf started; sleep 10'", timeout_seconds=1)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "started")
        self.assertIn("started", result.stderr)

    def test_signal_terminates_active_capture_and_replays_output(self) -> None:
        helper = shlex.quote(str(RELEASE_HELPER))
        shell = (
            f"source {helper}; capture_command {shlex.quote(str(self.output))} "
            f"{shlex.quote(str(self.stderr_file))} 20 "
            "/usr/bin/python3 -c 'import time; print(\"started\", flush=True); time.sleep(20)'"
        )
        process = subprocess.Popen(
            ["/bin/bash", "-euo", "pipefail", "-c", shell],
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            for _ in range(100):
                if self.output.exists() and self.output.read_text(encoding="utf-8") == "started\n":
                    break
                if process.poll() is not None:
                    self.fail("capture command exited before signal test started")
                time.sleep(0.02)
            else:
                self.fail("capture command did not start")
            os.killpg(process.pid, 15)
            _stdout, stderr = process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, 9)
                process.communicate(timeout=5)
        self.assertEqual(process.returncode, 143, stderr.decode(errors="replace"))
        self.assertIn(b"started", stderr)


class ReleaseEvidenceTests(unittest.TestCase):

    def test_registry_login_uses_missing_authfile_and_password_stdin(self) -> None:
        """The login path must let Skopeo create its JSON auth file, without leaking the token."""
        helper = CONTAINER_HELPER
        with tempfile.TemporaryDirectory(delete=False, prefix="server-state-skopeo-login-") as directory:
            root = Path(directory)
            fake_skopeo = root / "skopeo"
            fake_skopeo.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "[ \"${1:-}\" = login ]\n"
                "shift\n"
                "authfile=\n"
                "while [ $# -gt 0 ]; do\n"
                "  case \"$1\" in\n"
                "    --authfile) authfile=$2; shift 2 ;;\n"
                "    *) shift ;;\n"
                "  esac\n"
                "done\n"
                "[ -n \"$authfile\" ]\n"
                "[ ! -e \"$authfile\" ]\n"
                "printf '%s' absent > \"$AUTHFILE_STATE\"\n"
                "token=$(cat)\n"
                "printf '%s' \"$token\" > \"$TOKEN_CAPTURE\"\n"
                "printf '%s' '{\"auths\":{\"ghcr.io\":{\"auth\":\"offline\"}}}' > \"$authfile\"\n",
                encoding="utf-8",
            )
            fake_skopeo.chmod(0o755)
            authfile_state = root / "authfile-state"
            token_capture = root / "token-capture"
            login_output = root / "login.stdout"
            command = (
                f"source {shlex.quote(str(helper))}; "
                f"export PATH={shlex.quote(str(root))}:$PATH; "
                "authdir=\"$(mktemp -d)\"; "
                "authfile=\"$authdir/auth.json\"; "
                "cleanup() { rm -rf \"$authdir\"; }; trap cleanup EXIT; "
                "registry_token='offline-registry-token'; "
                f"AUTHFILE_STATE={shlex.quote(str(authfile_state))} "
                f"TOKEN_CAPTURE={shlex.quote(str(token_capture))} "
                f"export AUTHFILE_STATE TOKEN_CAPTURE; "
                f"printf '%s' \"$registry_token\" | container_command --sensitive --inherit-stdin "
                f"{shlex.quote(str(login_output))} 30 skopeo login --authfile \"$authfile\" "
                "--username actor --password-stdin ghcr.io"
            )
            result = subprocess.run(
                ["/bin/bash", "-c", command],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(authfile_state.read_text(encoding="utf-8"), "absent")
            self.assertEqual(token_capture.read_text(encoding="utf-8"), "offline-registry-token")
            self.assertNotIn("offline-registry-token", result.stdout + result.stderr)

    def test_product_tag_evidence_uses_tag_identity_not_response_urls(self) -> None:
        key = "SYNAPSE_IMAGE"
        tag = validate.load_manifest()[key].rsplit(":", 1)[1]
        repository = validate.PUBLIC_RELEASES[key]["repository"]
        annotated_tag_sha = "b" * 40
        source_commit = "a" * 40
        api_root = f"https://api.github.com/repos/{repository}"
        tag_ref = {
            "ref": f"refs/tags/{tag}",
            "url": f"{api_root}/git/refs/tags/{tag}",
            "object": {
                "type": "tag",
                "sha": annotated_tag_sha,
                "url": f"{api_root}/git/tags/{annotated_tag_sha}",
            },
        }
        annotated_tag = {
            "sha": annotated_tag_sha,
            "tag": tag,
            "url": f"{api_root}/git/tags/{annotated_tag_sha}",
            "object": {
                "type": "commit",
                "sha": source_commit,
                "url": f"{api_root}/git/commits/{source_commit}",
            },
        }
        validate.validate_product_tag_evidence(
            key, tag, source_commit, annotated_tag_sha, tag_ref, annotated_tag
        )
        invalid = {**annotated_tag, "object": {**annotated_tag["object"], "sha": "c" * 40}}
        with self.assertRaises(AssertionError):
            validate.validate_product_tag_evidence(
                key, tag, source_commit, annotated_tag_sha, tag_ref, invalid
            )

    def test_product_asset_schema_keeps_required_fields_and_allows_metadata(self) -> None:
        raw = (
            b'{"annotated_tag_sha":"' + b"b" * 40 + b'","digest":"sha256:' + b"a" * 64 +
            b'","image":"repo/image","schema_version":1,"source_commit":"' + b"a" * 40 +
            b'","tag":"1.0.0"}\n'
        )
        self.assertEqual(validate.parse_product_release_asset("SYNAPSE_IMAGE", raw)["tag"], "1.0.0")
        self.assertEqual(validate.parse_product_release_asset("SYNAPSE_IMAGE", raw[:-1] + b" ") ["tag"], "1.0.0")
        self.assertEqual(
            validate.parse_product_release_asset(
                "SYNAPSE_IMAGE",
                raw.replace(b'"tag":"1.0.0"', b'"extra":true,"tag":"1.0.0"')[:-1],
            )["tag"],
            "1.0.0",
        )
        with self.assertRaises(AssertionError):
            validate.parse_product_release_asset("CASHIER_IMAGE", raw)

    def test_cashier_manifest_shape_and_oci_provenance_are_strict(self) -> None:
        image = validate.load_manifest()["CASHIER_IMAGE"]
        labels = {
            "org.opencontainers.image.source": "https://github.com/TeleCrypt-io/cashier",
            "org.opencontainers.image.version": image.rsplit(":", 1)[1],
            "org.opencontainers.image.revision": "a" * 40,
        }
        self.assertNotIn("CASHIER_IMAGE", validate.PUBLIC_RELEASES)
        self.assertEqual(
            validate.validate_cashier_provenance(labels, image),
            {"source": labels["org.opencontainers.image.source"], "version": labels["org.opencontainers.image.version"], "revision": labels["org.opencontainers.image.revision"]},
        )
        self.assertEqual(validate.IMAGE_RECORD_KEYS, {"digest", "image"})
        for field, value in (
            ("org.opencontainers.image.source", "https://github.com/TeleCrypt-io/other"),
            ("org.opencontainers.image.version", "0.0.0"),
            ("org.opencontainers.image.revision", "not-a-commit"),
        ):
            mutated = {**labels, field: value}
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate.validate_cashier_provenance(mutated, image)

    def test_image_release_manifest_serializes_only_exact_image_digest_records(self) -> None:
        values = validate.load_manifest()
        digest = "sha256:" + "a" * 64
        metadata = {key: {"Name": image.rsplit(":", 1)[0], "Digest": digest} for key, image in values.items()}
        labels = {
            key: {
                "org.opencontainers.image.source": f"https://github.com/TeleCrypt-io/{'synapse-server' if key == 'SYNAPSE_IMAGE' else 'control-plane'}",
                "org.opencontainers.image.version": image.rsplit(":", 1)[1],
                "org.opencontainers.image.revision": "b" * 40,
            }
            for key, image in values.items()
            if key in validate.PUBLIC_RELEASE_KEYS
        }
        labels["CASHIER_IMAGE"] = {
            "org.opencontainers.image.source": "https://github.com/TeleCrypt-io/cashier",
            "org.opencontainers.image.version": values["CASHIER_IMAGE"].rsplit(":", 1)[1],
            "org.opencontainers.image.revision": "c" * 40,
        }

        def fake_release(key: str, image: str, _digest: str, provenance: dict, *_evidence: object) -> dict:
            release = {field: "fixture" for field in validate.PRODUCT_RELEASE_RECORD_KEYS}
            release["source_commit"] = provenance["org.opencontainers.image.revision"]
            return release

        with mock.patch.object(validate, "validate_product_release", side_effect=fake_release):
            document = validate.image_release_manifest(
                values,
                metadata,
                labels,
                "server-state-abc1234-42",
                "d" * 40,
                "e" * 40,
                product_releases={key: {} for key in validate.PUBLIC_RELEASE_KEYS},
                product_assets={key: b"fixture" for key in validate.PUBLIC_RELEASE_KEYS},
                product_tag_refs={key: {"fixture": True} for key in validate.PUBLIC_RELEASE_KEYS},
                product_annotated_tags={key: {"fixture": True} for key in validate.PUBLIC_RELEASE_KEYS},
                resolved_digests={key: digest for key in values},
            )
        for key, record in document["images"].items():
            with self.subTest(key=key):
                self.assertEqual(set(record), validate.IMAGE_RECORD_KEYS)
                validate.validate_image_record(key, record)
        cashier_with_extra = {**document["images"]["CASHIER_IMAGE"], "release": {}}
        with self.assertRaises(AssertionError):
            validate.validate_image_record("CASHIER_IMAGE", cashier_with_extra)

    def test_product_release_fetch_reports_safe_request_identity_on_api_failure(self) -> None:
        script = Path(__file__).parent / "fetch_product_releases.sh"
        with tempfile.TemporaryDirectory(delete=False, prefix="server-state-gh-unauthorized-") as directory:
            root = Path(directory)
            fake_gh = root / "gh"
            fake_gh.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'gh: Not Found (HTTP 404)' >&2\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake_gh.chmod(0o755)
            result = subprocess.run(
                ["/bin/bash", str(script)],
                cwd=script.parents[2],
                env={
                    **os.environ,
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "GH_TOKEN": "offline-test-token",
                    "METADATA_DIR": str(root / "metadata"),
                },
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("phase=tag-ref", result.stderr)
            self.assertIn("repository=TeleCrypt-io/synapse-server", result.stderr)
            synapse_tag = validate.load_manifest()["SYNAPSE_IMAGE"].rsplit(":", 1)[1]
            self.assertIn(f"tag={synapse_tag}", result.stderr)
            self.assertNotIn("offline-test-token", result.stdout + result.stderr)

    def test_container_command_explicit_stdin_inheritance_is_secret_safe(self) -> None:
        with tempfile.TemporaryDirectory(delete=False, prefix="server-state-stdin-") as directory:
            root = Path(directory)
            output = root / "output"
            secret = "offline-fixture-secret\n"
            child = (
                "import sys; value=sys.stdin.read(); "
                "assert value == 'offline-fixture-secret\\n'; "
                "sys.stdout.write(value); sys.stderr.write(value)"
            )
            command = (
                f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                f"container_command --sensitive --inherit-stdin {shlex.quote(str(output))} 10 "
                f"/usr/bin/python3 -c {shlex.quote(child)}"
            )
            result = subprocess.run(
                ["/bin/bash", "-c", command],
                cwd=root,
                input=secret,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            transcript = result.stdout + result.stderr
            self.assertNotIn(secret, transcript)
            self.assertEqual(output.read_text(encoding="utf-8"), secret)
            self.assertEqual(Path(f"{output}.stderr").read_text(encoding="utf-8"), secret)

    def test_container_command_keeps_stdin_closed_by_default(self) -> None:
        with tempfile.TemporaryDirectory(delete=False, prefix="server-state-stdin-closed-") as directory:
            root = Path(directory)
            output = root / "output"
            secret = "offline-secret-must-not-reach-child\n"
            child = "import sys; assert sys.stdin.read() == ''; print('stdin closed')"
            command = (
                f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                f"container_command {shlex.quote(str(output))} 10 "
                f"/usr/bin/python3 -c {shlex.quote(child)}"
            )
            result = subprocess.run(
                ["/bin/bash", "-c", command],
                cwd=root,
                input=secret,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            transcript = result.stdout + result.stderr + output.read_text(encoding="utf-8")
            self.assertIn("stdin closed", transcript)
            self.assertNotIn(secret, transcript)


if __name__ == "__main__":
    unittest.main()
