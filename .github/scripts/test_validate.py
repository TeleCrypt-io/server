#!/usr/bin/env python3
"""Focused semantic tests for Server State validation and release evidence."""

from __future__ import annotations

import os
import json
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

sys.path.insert(0, str(Path(__file__).parent))
import validate  # noqa: E402


CONTAINER_HELPER = Path(__file__).parent / "container-helpers.sh"
RELEASE_HELPER = Path(__file__).parent / "release-helpers.sh"
WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "validate.yml"


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
    def validate_source_with_read_text(self, replacements: dict[Path, str]) -> None:
        original_read_text = Path.read_text
        replacement_text = {path.resolve(): text for path, text in replacements.items()}

        def read_text(path: Path, *args: object, **kwargs: object) -> str:
            replacement = replacement_text.get(path.resolve())
            if replacement is not None:
                return replacement
            return original_read_text(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", new=read_text):
            validate.validate_source(validate.load_manifest())

    def test_billing_profile_validation_accepts_only_known_pairs(self) -> None:
        self.assertEqual(
            validate.VALID_PROFILES,
            {("telecrypt.io", "test"), ("stage.telecrypt.io", "test"), ("telecrypt.io", "live")},
        )
        for profile in validate.VALID_PROFILES:
            self.assertEqual(validate.validate_profile({"SERVER_NAME": profile[0], "BILLING_ENVIRONMENT": profile[1]}), profile)
        for profile in (("stage.telecrypt.io", "live"), ("other.telecrypt.io", "test"), ("telecrypt.io", "sandbox")):
            with self.assertRaises(AssertionError):
                validate.validate_profile({"SERVER_NAME": profile[0], "BILLING_ENVIRONMENT": profile[1]})
    def test_synapse_prejoin_state_is_narrow_and_covers_nested_folders(self) -> None:
        root = Path(__file__).resolve().parents[2]
        synapse = (root / "synapse.yaml").read_text(encoding="utf-8")
        validate.validate_synapse_prejoin_state(synapse)
        mutations = (
            synapse.replace("room_prejoin_state:\n", "", 1),
            synapse.replace(
                "- [org.matrix.msc3088.purpose, org.matrix.msc3089.data_tree]",
                "- [org.matrix.msc3088.purpose, org.example.other]",
                1,
            ),
            synapse.replace(
                "- m.space.parent",
                "- [m.space.parent, !fixed:example.test]",
                1,
            ),
            synapse.replace(
                "  additional_event_types:\n",
                "  disable_default_event_types: true\n  additional_event_types:\n",
                1,
            ),
        )
        for candidate in mutations:
            with self.assertRaises(AssertionError):
                validate.validate_synapse_prejoin_state(candidate)

    def test_mas_listener_validator_rejects_unsupported_binds_and_resources(self) -> None:
        mas = (Path(__file__).resolve().parents[2] / "mas.yaml").read_text(encoding="utf-8")
        validate.validate_mas_listeners(mas)

        alias_bind = mas.replace(
            "- address: '0.0.0.0:8080'",
            "- host: mas-edge\n          port: 8080",
            1,
        )
        with self.assertRaises(AssertionError):
            validate.validate_mas_listeners(alias_bind)

        internal_oauth = "        - name: oauth          # Plan/Janitor client-credentials token endpoint; no public route\n"
        mutations = (
            mas.replace(internal_oauth, "", 1),
            mas.replace(internal_oauth, internal_oauth + "        - name: health\n", 1),
            mas.replace("        - name: assets\n", "        - name: assets\n        - name: health\n", 1),
        )
        for candidate in mutations:
            with self.assertRaises(AssertionError):
                validate.validate_mas_listeners(candidate)

    def test_matrix_private_layers_own_complete_shallow_merged_maps(self) -> None:
        root = Path(__file__).resolve().parents[2]
        compose = yaml.safe_load((root / "compose.yml").read_text(encoding="utf-8"))
        synapse = yaml.safe_load((root / "synapse.yaml").read_text(encoding="utf-8"))
        mas = yaml.safe_load((root / "mas.yaml").read_text(encoding="utf-8"))
        mas_fixture = json.loads((root / ".github" / "fixtures" / "mas.secrets.json").read_text(encoding="utf-8"))
        synapse_fixture = json.loads((root / ".github" / "fixtures" / "synapse.secrets.json").read_text(encoding="utf-8"))
        signing_fixture = (Path(__file__).resolve().parents[1] / "fixtures" / "synapse-signing-fixture.txt").read_text(encoding="utf-8")
        self.assertIn("SYNAPSE_SECRETS_JSON", validate.SECRET_ENV.values())
        self.assertIn("MAS_SECRETS_JSON", validate.SECRET_ENV.values())
        self.assertIn(
            {"source": "synapse_secrets_json", "target": "/secrets.json"},
            compose["services"]["synapse"]["secrets"],
        )
        self.assertIn(
            {"source": "mas_secrets_json", "target": "/secrets.json"},
            compose["services"]["mas"]["secrets"],
        )
        self.assertNotIn("database", synapse)
        self.assertNotIn("matrix_authentication_service", synapse)
        self.assertIs(synapse["dynamic_thumbnails"], False)
        self.assertEqual(synapse["thumbnail_sizes"], [])
        self.assertEqual(mas["matrix"], {"kind": "synapse", "endpoint": "http://synapse:8008"})
        self.assertEqual(mas["email"]["transport"], "blackhole")
        self.assertIs(mas["account"]["account_deactivation_allowed"], True)
        self.assertEqual(mas["policy"]["client_registration_entrypoint"], "client_registration/violation")
        self.assertNotIn("database", mas)
        self.assertEqual(synapse_fixture["database"]["name"], "psycopg2")
        self.assertEqual(
            set(synapse_fixture["database"]["args"]),
            {"user", "password", "database", "host", "port", "sslmode", "connect_timeout"},
        )
        self.assertEqual(
            synapse_fixture["matrix_authentication_service"],
            {"enabled": True, "endpoint": "http://mas:8080", "secret": "ci-matrix-secret"},
        )
        self.assertEqual(
            synapse_fixture["media_storage_providers"][0]["config"]["endpoint_url"],
            "https://sss.telecrypt.io",
        )
        self.assertRegex(signing_fixture, r"\Aed25519 0 [A-Za-z0-9+/]{43}\n\Z")
        self.assertEqual(
            [client["client_auth_method"] for client in mas_fixture["clients"]],
            ["client_secret_basic", "client_secret_basic"],
        )

    def test_source_validation_does_not_depend_on_synapse_explanatory_comments(self) -> None:
        synapse_path = validate.ROOT / "synapse.yaml"
        synapse = synapse_path.read_text(encoding="utf-8")
        without_full_line_comments = "\n".join(
            line for line in synapse.splitlines() if not line.lstrip().startswith("#")
        ) + "\n"

        self.validate_source_with_read_text({synapse_path: without_full_line_comments})

    def test_source_validation_rejects_database_in_synapse_base(self) -> None:
        synapse_path = validate.ROOT / "synapse.yaml"
        synapse = synapse_path.read_text(encoding="utf-8") + "\ndatabase:\n  name: psycopg2\n"

        with self.assertRaisesRegex(AssertionError, "Synapse complete private loader maps"):
            self.validate_source_with_read_text({synapse_path: synapse})

    def test_source_validation_rejects_incomplete_synapse_private_map(self) -> None:
        fixture_path = validate.ROOT / ".github" / "fixtures" / "synapse.secrets.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture["matrix_authentication_service"]["enabled"] = False

        with self.assertRaisesRegex(AssertionError, "Synapse complete private loader maps"):
            self.validate_source_with_read_text({fixture_path: json.dumps(fixture)})

    def test_caddy_capability_exception_is_exact_and_non_caddy_stays_capability_free(self) -> None:
        compose = yaml.safe_load((Path(__file__).resolve().parents[2] / "compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(services["caddy"]["cap_drop"], ["ALL"])
        self.assertEqual(services["caddy"]["cap_add"], ["NET_BIND_SERVICE"])
        validate.validate_service_capabilities("caddy", services["caddy"])
        with self.assertRaises(AssertionError):
            validate.validate_service_capabilities(
                "caddy", {**services["caddy"], "cap_add": ["NET_ADMIN"]}
            )
        with self.assertRaises(AssertionError):
            validate.validate_service_capabilities("caddy", {key: value for key, value in services["caddy"].items() if key != "cap_add"})
        for service, settings in services.items():
            if service == "caddy":
                continue
            self.assertNotIn("cap_add", settings)
            validate.validate_service_capabilities(service, settings)
            with self.assertRaises(AssertionError):
                validate.validate_service_capabilities(
                    service, {**settings, "cap_add": ["NET_ADMIN"]}
                )
    def test_manifest_has_exactly_five_versioned_images(self) -> None:
        values = validate.load_manifest()
        self.assertEqual(set(values), set(validate.IMAGE_KEYS))
        self.assertEqual(len(set(values.values())), len(validate.IMAGE_KEYS))
        with self.assertRaises(AssertionError):
            validate.parse_manifest([*(f"{key}={value}" for key, value in values.items()), "EXTRA=x:1"])

    def test_version_and_toolchain_validation_rejects_malformed_values(self) -> None:
        validate.version_tuple("24.0.9", "engine")
        validate.validate_toolchain("28.0.0", "2.40.0")
        for value in ("", "1.2", "1.2.3.4"):
            with self.assertRaises(AssertionError):
                validate.version_tuple(value, "version")

    def test_image_platform_and_provenance_are_bound(self) -> None:
        controlplane_version = validate.load_manifest()["CONTROLPLANE_IMAGE"].rsplit(":", 1)[1]
        validate.validate_image_platform(
            {"Os": "linux", "Architecture": "amd64", "Digest": "sha256:" + "a" * 64},
            {"os": "linux", "architecture": "amd64"},
        )
        labels = {
            "org.opencontainers.image.source": "https://github.com/TeleCrypt-io/telecrypt-synapse",
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
            "org.opencontainers.image.source": "https://github.com/TeleCrypt-io/telecrypt-synapse",
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
                "org.opencontainers.image.source": f"https://github.com/TeleCrypt-io/{'controlplane' if key == 'CONTROLPLANE_IMAGE' else 'cashier'}",
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


class AdaptedCaddyTests(unittest.TestCase):
    def test_adapted_ingress_peer_gate_rejects_untrusted_before_terminal_fallback(self) -> None:
        def site_routes() -> list[dict]:
            return [
                {
                    "match": [{"not": [{"remote_ip": {"ranges": ["192.0.2.10/32"]}}]}],
                    "handle": [{
                        "handler": "subroute",
                        "routes": [{"handle": [{"handler": "static_response", "abort": True}]}],
                    }],
                },
                {
                    "handle": [{
                        "handler": "subroute",
                        "routes": [{"handle": [{"handler": "static_response"}]}],
                    }],
                },
            ]

        document = {
            "apps": {
                "http": {
                    "servers": {
                        "srv0": {
                            "routes": [
                                {"handle": [{"handler": "subroute", "routes": site_routes()}]},
                                {"handle": [{"handler": "subroute", "routes": site_routes()}]},
                            ]
                        }
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory(delete=False, prefix="server-state-caddy-adapted-") as directory:
            path = Path(directory) / "adapted.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            validate.validate_adapted_caddy(path)

            reordered = json.loads(path.read_text(encoding="utf-8"))
            routes = reordered["apps"]["http"]["servers"]["srv0"]["routes"][0]["handle"][0]["routes"]
            routes.reverse()
            path.write_text(json.dumps(reordered), encoding="utf-8")
            with self.assertRaises(AssertionError):
                validate.validate_adapted_caddy(path)


class ReleaseWorkflowGitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(delete=False, prefix="server-state-release-git-")
        self.root = Path(self.directory.name)
        self.seed = self.root / "seed"
        self.seed.mkdir()
        self.origin = self.root / "origin.git"
        self.checkout = self.root / "checkout"
        subprocess.run(["/usr/bin/git", "init", "--bare", "--quiet", str(self.origin)], check=True)
        git(self.seed, "init", "--quiet")
        self.commit_file("first\n", "first")
        git(self.seed, "branch", "-M", "main")
        self.first_commit = git(self.seed, "rev-parse", "HEAD")
        self.commit_file("second\n", "second")
        self.release_commit = git(self.seed, "rev-parse", "HEAD")
        self.tag = f"server-state-{self.release_commit[:8]}"
        git(self.seed, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "tag", "-a", self.tag, "-m", "release", self.release_commit)
        self.annotated_tag_sha = git(self.seed, "rev-parse", f"refs/tags/{self.tag}")
        self.commit_file("third\n", "main advanced")
        self.main_commit = git(self.seed, "rev-parse", "HEAD")
        git(self.seed, "remote", "add", "origin", str(self.origin))
        git(self.seed, "push", "--quiet", "origin", "main", f"refs/tags/{self.tag}")
        self.make_checkout(self.tag)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def commit_file(self, contents: str, message: str) -> None:
        (self.seed / "fixture").write_text(contents, encoding="utf-8")
        git(self.seed, "add", "fixture")
        git(self.seed, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "--quiet", "-m", message)

    def make_checkout(self, tag: str) -> None:
        if self.checkout.exists():
            subprocess.run(["/bin/rm", "-rf", str(self.checkout)], check=True)
        subprocess.run(["/usr/bin/git", "clone", "--quiet", "--no-checkout", str(self.origin), str(self.checkout)], check=True)
        git(self.checkout, "fetch", "--quiet", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
        git(self.checkout, "checkout", "--quiet", "--detach", f"refs/tags/{tag}")

    def run_workflow_step(self, job: str, step_id: str, **environment: str) -> subprocess.CompletedProcess[str]:
        output = self.root / "github-output"
        output.write_text("", encoding="utf-8")
        return subprocess.run(
            ["/bin/bash", "-euo", "pipefail", "-c", workflow_run(job, step_id)],
            cwd=self.checkout,
            env={
                **os.environ,
                "GITHUB_OUTPUT": str(output),
                **environment,
            },
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def validate_tag(self, tag: str | None = None, event_commit: str | None = None) -> subprocess.CompletedProcess[str]:
        return self.run_workflow_step(
            "validate",
            "release_identity",
            GITHUB_REF_NAME=tag or self.tag,
            GITHUB_SHA=event_commit or self.release_commit,
        )

    def test_annotated_tag_is_accepted_when_main_has_advanced(self) -> None:
        result = self.validate_tag()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.main_commit, self.release_commit)
        recorded = (self.root / "github-output").read_text(encoding="utf-8")
        self.assertEqual(recorded, f"release_commit={self.release_commit}\nannotated_tag_sha={self.annotated_tag_sha}\n")

    def test_lightweight_tag_is_rejected(self) -> None:
        git(self.seed, "tag", "-d", self.tag)
        git(self.seed, "tag", self.tag, self.release_commit)
        git(self.seed, "push", "--quiet", "--force", "origin", f"refs/tags/{self.tag}")
        self.make_checkout(self.tag)
        result = self.validate_tag()
        self.assertNotEqual(result.returncode, 0)

    def test_wrong_commit_suffix_is_rejected(self) -> None:
        wrong_prefix = ("0" if self.release_commit[0] != "0" else "1") + self.release_commit[1:8]
        wrong_tag = f"server-state-{wrong_prefix}"
        git(self.seed, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "tag", "-a", wrong_tag, "-m", "wrong suffix", self.release_commit)
        git(self.seed, "push", "--quiet", "origin", f"refs/tags/{wrong_tag}")
        self.make_checkout(wrong_tag)
        result = self.validate_tag(wrong_tag)
        self.assertNotEqual(result.returncode, 0)

    def test_event_commit_must_match_annotated_tag_target(self) -> None:
        result = self.validate_tag(event_commit=self.main_commit)
        self.assertNotEqual(result.returncode, 0)

    def test_release_commit_outside_main_history_is_rejected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        git(outside, "init", "--quiet")
        (outside / "fixture").write_text("outside\n", encoding="utf-8")
        git(outside, "add", "fixture")
        git(outside, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "--quiet", "-m", "outside")
        outside_commit = git(outside, "rev-parse", "HEAD")
        outside_tag = f"server-state-{outside_commit[:8]}"
        git(outside, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "tag", "-a", outside_tag, "-m", "outside")
        git(outside, "remote", "add", "origin", str(self.origin))
        git(outside, "push", "--quiet", "origin", f"refs/tags/{outside_tag}")
        self.make_checkout(outside_tag)
        result = self.validate_tag(outside_tag, outside_commit)
        self.assertNotEqual(result.returncode, 0)

    def test_release_job_requires_the_recorded_checkout_and_tag_object(self) -> None:
        good = self.run_workflow_step(
            "release",
            "selected_release_identity",
            GITHUB_REF_NAME=self.tag,
            GITHUB_SHA=self.release_commit,
            RELEASE_COMMIT=self.release_commit,
            RELEASE_ANNOTATED_TAG_SHA=self.annotated_tag_sha,
        )
        self.assertEqual(good.returncode, 0, good.stderr)
        changed = self.run_workflow_step(
            "release",
            "selected_release_identity",
            GITHUB_REF_NAME=self.tag,
            GITHUB_SHA=self.release_commit,
            RELEASE_COMMIT=self.release_commit,
            RELEASE_ANNOTATED_TAG_SHA=self.first_commit,
        )
        self.assertNotEqual(changed.returncode, 0)
        changed_commit = self.run_workflow_step(
            "release",
            "selected_release_identity",
            GITHUB_REF_NAME=self.tag,
            GITHUB_SHA=self.release_commit,
            RELEASE_COMMIT=self.main_commit,
            RELEASE_ANNOTATED_TAG_SHA=self.annotated_tag_sha,
        )
        self.assertNotEqual(changed_commit.returncode, 0)


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

    def test_container_diagnostics_accept_progress_and_reject_hostile_markers(self) -> None:
        with tempfile.TemporaryDirectory(delete=False, prefix="server-state-container-diagnostics-") as directory:
            root = Path(directory)

            def run(
                code: str,
                timeout: int = 10,
                *,
                sensitive: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                output = root / "output"
                option = "--sensitive " if sensitive else ""
                command = (
                    f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                    f"container_command {option}{shlex.quote(str(output))} {timeout} "
                    f"/usr/bin/python3 -c {shlex.quote(code)}"
                )
                return subprocess.run(
                    ["/bin/bash", "-c", command],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=12,
                    check=False,
                )

            progress = run("import sys; sys.stdout.write('digest\\n'); sys.stderr.write('progress: exporting layers\\n')")
            self.assertEqual(progress.returncode, 0, progress.stderr)
            self.assertEqual(progress.stdout, "digest\n")
            self.assertIn("progress: exporting layers", progress.stderr)
            self.assertNotIn("failure diagnostics", progress.stderr)

            for marker in ("warning", "WARN", "error", "fatal", "failure", "denied", "unauthorized"):
                result = run(f"import sys; sys.stdout.write('partial\\n'); sys.stderr.write('{marker}: hostile fixture\\n')")
                self.assertEqual(result.returncode, 0, marker)
                self.assertEqual(result.stdout, "partial\n", marker)
                self.assertIn("hostile fixture", result.stderr, marker)
                self.assertNotIn("failure diagnostics", result.stderr, marker)

            boundary = run("import sys; sys.stderr.write('warningish error_code\\n')")
            self.assertEqual(boundary.returncode, 0, boundary.stderr)
            self.assertNotIn("failure diagnostics", boundary.stderr)

            sensitive = run(
                "import sys; sys.stdout.write('private stdout\\n'); "
                "sys.stderr.write('warning: private stderr\\n')",
                sensitive=True,
            )
            self.assertEqual(sensitive.returncode, 0)
            self.assertIn("private [redacted]", sensitive.stdout + sensitive.stderr)
            self.assertNotIn("stdout", sensitive.stdout + sensitive.stderr)
            self.assertNotIn("stderr", sensitive.stdout + sensitive.stderr)

            api_key = run(
                "import sys; sys.stdout.write('DODO_API_KEY=synthetic-secret-value\\napiKey: synthetic-secret-value\\n'); "
                "sys.stderr.write('api-key: synthetic-secret-value\\n'); raise SystemExit(17)",
                sensitive=True,
            )
            self.assertEqual(api_key.returncode, 17)
            self.assertNotIn("synthetic-secret-value", api_key.stdout + api_key.stderr)
            self.assertIn("DODO_API_KEY=[redacted]", api_key.stdout + api_key.stderr)
            self.assertIn("apiKey: [redacted]", api_key.stdout + api_key.stderr)
            self.assertIn("api-key: [redacted]", api_key.stdout + api_key.stderr)

            failed = run("import sys; sys.stdout.write('partial\\n'); sys.stderr.write('ordinary diagnostic\\n'); raise SystemExit(17)")
            self.assertEqual(failed.returncode, 17, failed.stderr)
            self.assertIn("partial", failed.stderr)
            self.assertIn("ordinary diagnostic", failed.stderr)

            timed_out = run("import time; time.sleep(60)", timeout=1)
            self.assertEqual(timed_out.returncode, 124, timed_out.stderr)

    def test_sensitive_proof_failures_have_fixed_classes_without_diagnostics(self) -> None:
        classifications = {
            "success": "success",
            "uid": "uid",
            "mount-content": "mount-content",
            "secrets-json": "secrets-json",
            "forbidden-mount": "forbidden-mount",
            "environment-leak": "environment-leak",
        }
        with tempfile.TemporaryDirectory(delete=False, prefix="server-state-sensitive-class-") as directory:
            root = Path(directory)
            for marker, expected in classifications.items():
                result = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        f"source {shlex.quote(str(CONTAINER_HELPER))}; container_sensitive_failure_class {shlex.quote(marker)}",
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, marker)
                self.assertEqual(result.stdout, expected + "\n", marker)
                self.assertEqual(result.stderr, "", marker)

                marker_file = root / "marker"
                marker_file.write_text(f"telecrypt-synapse-proof:{marker}\n", encoding="utf-8")
                parsed = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        f"source {shlex.quote(str(CONTAINER_HELPER))}; container_sensitive_marker_class {shlex.quote(str(marker_file))}",
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(parsed.returncode, 0, marker)
                self.assertEqual(parsed.stdout, expected + "\n", marker)
                self.assertEqual(parsed.stderr, "", marker)

            signing_fixture = (Path(__file__).resolve().parents[1] / "fixtures" / "synapse-signing-fixture.txt").read_text(encoding="utf-8").strip()
            for hostile in (
                signing_fixture,
                f"telecrypt-synapse-proof:uid\n{signing_fixture}",
                "telecrypt-synapse-proof:uid\nnot-a-marker",
            ):
                marker_file = root / "hostile-marker"
                marker_file.write_text(hostile, encoding="utf-8")
                rejected = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        f"source {shlex.quote(str(CONTAINER_HELPER))}; container_sensitive_marker_class {shlex.quote(str(marker_file))}",
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(rejected.returncode, 0, hostile)
                self.assertEqual(rejected.stdout, "", hostile)
                self.assertEqual(rejected.stderr, "", hostile)

            marker_file = root / "marker"
            stderr_file = root / "stderr"
            marker_file.write_text("telecrypt-synapse-proof:success\n", encoding="utf-8")
            stderr_file.write_text("warning: private diagnostic\n", encoding="utf-8")
            rejected_stderr = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                    f"container_sensitive_proof_class 1 {shlex.quote(str(marker_file))} {shlex.quote(str(stderr_file))}",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(rejected_stderr.returncode, 0)
            self.assertEqual(rejected_stderr.stdout, "stderr-diagnostics\n")
            self.assertEqual(rejected_stderr.stderr, "")

            no_marker = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                    f"container_sensitive_proof_class 1 {shlex.quote(str(root / 'missing'))} {shlex.quote(str(stderr_file))}",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(no_marker.returncode, 0)
            self.assertEqual(no_marker.stdout, "unknown\n")
            self.assertEqual(no_marker.stderr, "")
            self.assertEqual(
                stderr_file.read_text(encoding="utf-8"), "warning: private diagnostic\n"
            )

            preflight_cases = {
                "Error response from daemon: manifest unknown: private-fixture": "image-pull",
                "unauthorized: authentication required for ci-secret-fixture": "registry-auth",
                "invalid mount config for type bind: bind source path does not exist: ci-secret-fixture": "mount-source",
                'OCI runtime create failed: exec: "python": executable file not found in $PATH ci-secret-fixture': "entrypoint-executable",
                "failed to create secret ci-secret-fixture: secret not found": "compose-secrets",
                "secret source file does not exist: ci-secret-fixture": "compose-secrets",
                "permission denied while opening ci-secret-fixture": "runtime-permission",
                "operation not permitted while opening ci-secret-fixture": "runtime-permission",
                "read-only file system while opening ci-secret-fixture": "runtime-permission",
                "not a directory: ci-secret-fixture": "file-shape",
                "no such file or directory: ci-secret-fixture": "file-shape",
                "OCI runtime create failed while mounting ci-secret-fixture": "oci-runtime",
                "Cannot connect to the Docker daemon at unix:///var/run/docker.sock: ci-secret-fixture": "daemon-resource",
                "bounded command timed out while handling ci-secret-fixture": "timeout",
            }
            preflight_file = root / "preflight-stderr"
            for diagnostic, expected in preflight_cases.items():
                preflight_file.write_text(diagnostic + "\n", encoding="utf-8")
                classified = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                        f"container_sensitive_preflight_class {shlex.quote(str(preflight_file))}",
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(classified.returncode, 0, diagnostic)
                self.assertEqual(classified.stdout, expected + "\n", diagnostic)
                self.assertEqual(classified.stderr, "", diagnostic)
                self.assertNotIn("ci-secret-fixture", classified.stdout + classified.stderr, diagnostic)

                proof_class = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                        f"container_sensitive_proof_class 1 {shlex.quote(str(root / 'missing'))} "
                        f"{shlex.quote(str(preflight_file))}",
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(proof_class.returncode, 0, diagnostic)
                self.assertEqual(proof_class.stdout, expected + "\n", diagnostic)
                self.assertEqual(proof_class.stderr, "", diagnostic)
                self.assertNotIn("ci-secret-fixture", proof_class.stdout + proof_class.stderr, diagnostic)

            preflight_file.write_text("private fixture only: ci-secret-fixture\n", encoding="utf-8")
            generic_preflight = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                    f"container_sensitive_proof_class 1 {shlex.quote(str(root / 'missing'))} "
                    f"{shlex.quote(str(preflight_file))}",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(generic_preflight.returncode, 0)
            self.assertEqual(generic_preflight.stdout, "unknown\n")
            self.assertEqual(generic_preflight.stderr, "")
            self.assertEqual(
                preflight_file.read_text(encoding="utf-8"),
                "private fixture only: ci-secret-fixture\n",
            )
            self.assertNotIn("ci-secret-fixture", generic_preflight.stdout + generic_preflight.stderr)

            preflight_file.write_text("", encoding="utf-8")
            unknown_preflight = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                    f"container_sensitive_proof_class 1 {shlex.quote(str(root / 'missing'))} "
                    f"{shlex.quote(str(preflight_file))}",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(unknown_preflight.returncode, 0)
            self.assertEqual(unknown_preflight.stdout, "command-failure\n")
            self.assertEqual(unknown_preflight.stderr, "")

            output = root / "proof"
            failed = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                    f"container_command --sensitive {shlex.quote(str(output))} 10 "
                    "/usr/bin/python3 -c 'raise SystemExit(71)'",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(failed.returncode, 71)
            self.assertEqual(failed.stdout, "")
            self.assertEqual(failed.stderr, "")

            redirected_output = root / "redirected-proof"
            redirected = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    f"source {shlex.quote(str(CONTAINER_HELPER))}; "
                    f"container_command --sensitive {shlex.quote(str(redirected_output))} 10 "
                    "/usr/bin/python3 -c 'print(\"telecrypt-synapse-proof:uid\")' >/dev/null",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(redirected.returncode, 0)
            self.assertEqual(redirected.stdout, "")
            self.assertEqual(redirected.stderr, "")
            self.assertEqual(redirected_output.read_text(encoding="utf-8"), "telecrypt-synapse-proof:uid\n")

    def test_secret_proof_compose_matches_canonical_service_contract(self) -> None:
        proof_compose = yaml.safe_load((Path(__file__).resolve().parents[1] / "secret-proof.compose.yml").read_text(encoding="utf-8"))
        canonical_compose = yaml.safe_load((Path(__file__).resolve().parents[2] / "compose.yml").read_text(encoding="utf-8"))
        proof_services = proof_compose["services"]
        canonical_services = canonical_compose["services"]
        copied_fields = ("image", "user", "read_only", "security_opt", "cap_drop", "secrets")
        for proof_name, canonical_name in (
            ("synapse-secret-proof", "synapse"),
            ("synapse-loader-proof", "synapse"),
            ("mas-secret-proof", "mas"),
        ):
            for field in copied_fields:
                self.assertEqual(proof_services[proof_name][field], canonical_services[canonical_name][field], (proof_name, field))
            self.assertEqual(proof_services[proof_name]["network_mode"], "none")
            self.assertNotIn("networks", proof_services[proof_name])
            self.assertNotIn("depends_on", proof_services[proof_name])
        self.assertNotIn("volumes", proof_services["synapse-secret-proof"])
        self.assertIn(
            "../synapse.${SERVER_NAME:?set SERVER_NAME}.yaml:/synapse-environment.yaml:ro",
            proof_services["synapse-loader-proof"]["volumes"],
        )
        self.assertIn(
            "../synapse.telecrypt.io.yaml:/synapse-production-environment.yaml:ro",
            proof_services["synapse-loader-proof"]["volumes"],
        )
        self.assertEqual(
            proof_services["synapse-loader-proof"]["tmpfs"],
            [
                "/tmp:uid=991,gid=991,mode=1777",
                "/staging:uid=991,gid=991,mode=0700",
            ],
        )
        self.assertIn(
            "../mas.${SERVER_NAME:?set SERVER_NAME}.yaml:/mas-environment.yaml:ro",
            proof_services["mas-secret-proof"]["volumes"],
        )
        self.assertEqual(proof_services["synapse-loader-proof"]["environment"], ["TMPDIR=/staging/tmp"])
    def test_product_tag_evidence_binds_exact_api_urls(self) -> None:
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
        invalid = {**annotated_tag, "object": {**annotated_tag["object"], "url": f"{api_root}/git/commits/{source_commit}/unexpected"}}
        with self.assertRaises(AssertionError):
            validate.validate_product_tag_evidence(
                key, tag, source_commit, annotated_tag_sha, tag_ref, invalid
            )

    def test_product_asset_schema_is_strict(self) -> None:
        raw = (
            b'{"annotated_tag_sha":"' + b"b" * 40 + b'","digest":"sha256:' + b"a" * 64 +
            b'","image":"repo/image","schema_version":1,"source_commit":"' + b"a" * 40 +
            b'","tag":"1.0.0"}\n'
        )
        self.assertEqual(validate.parse_product_release_asset("SYNAPSE_IMAGE", raw)["tag"], "1.0.0")
        with self.assertRaises(AssertionError):
            validate.parse_product_release_asset("SYNAPSE_IMAGE", raw[:-1] + b" ")
        with self.assertRaises(AssertionError):
            validate.parse_product_release_asset("CASHIER_IMAGE", raw)

    def test_product_release_asset_label_is_exact_empty_string(self) -> None:
        self.assertEqual(validate.validate_release_asset_label("SYNAPSE_IMAGE", {"label": ""}), "")
        for label in (None, "asset-label"):
            with self.subTest(label=label), self.assertRaises(AssertionError):
                validate.validate_release_asset_label("SYNAPSE_IMAGE", {"label": label})

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
                "org.opencontainers.image.source": f"https://github.com/TeleCrypt-io/{'telecrypt-synapse' if key == 'SYNAPSE_IMAGE' else 'controlplane'}",
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
                "server-state-abc1234",
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
            self.assertIn("repository=TeleCrypt-io/telecrypt-synapse", result.stderr)
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
