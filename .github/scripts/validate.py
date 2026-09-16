#!/usr/bin/env python3
"""Validate the published image manifest and immutable release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMAGE_RULES = {
    "CADDY_IMAGE": ("docker.io/caddy", r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-alpine"),
    "SYNAPSE_IMAGE": ("ghcr.io/telecrypt-io/telecrypt-synapse", r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-tc(?:0|[1-9][0-9]*)"),
    "MAS_IMAGE": ("ghcr.io/element-hq/matrix-authentication-service", r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"),
    "CONTROLPLANE_IMAGE": ("ghcr.io/telecrypt-io/controlplane", r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"),
    "LK_JWT_IMAGE": ("ghcr.io/element-hq/lk-jwt-service", r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"),
    "CASHIER_IMAGE": ("ghcr.io/telecrypt-io/telecrypt-cashier", r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"),
}
IMAGE_KEYS = tuple(IMAGE_RULES)
UPSTREAM_RELEASES = {
    "CADDY_IMAGE": "caddyserver/caddy",
    "MAS_IMAGE": "element-hq/matrix-authentication-service",
    "LK_JWT_IMAGE": "element-hq/lk-jwt-service",
}
PRODUCT_RELEASES = {
    "SYNAPSE_IMAGE": {"repository": "TeleCrypt-io/synapse-server", "asset_prefix": "telecrypt-synapse-"},
    "CONTROLPLANE_IMAGE": {"repository": "TeleCrypt-io/control-plane", "asset_prefix": "controlplane-"},
    "CASHIER_IMAGE": {"repository": "TeleCrypt-io/cashier", "asset_prefix": "telecrypt-cashier-"},
}
PRODUCT_RELEASE_KEYS = frozenset(PRODUCT_RELEASES)
IMAGE_RECORD_KEYS = frozenset({"digest", "image"})
PRODUCT_RELEASE_RECORD_KEYS = {
    "asset", "asset_id", "asset_label", "asset_digest", "asset_size",
    "release_id", "source_commit", "tag", "annotated_tag_sha", "body",
}
SYNAPSE_LABELS = (
    "org.opencontainers.image.source", "org.opencontainers.image.revision", "org.opencontainers.image.version",
    "org.opencontainers.image.base.name", "org.opencontainers.image.base.version",
    "org.telecrypt.controlplane.release", "org.telecrypt.s3-provider.version",
    "org.telecrypt.controlplane.wheel.sha256", "org.telecrypt.s3-provider.fork.archive.sha256",
)
IMAGE_CONFIG = {
    "CADDY_IMAGE": {"Entrypoint": None, "Cmd": ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]},
    "MAS_IMAGE": {"Entrypoint": ["/usr/local/bin/mas-cli"], "Cmd": None},
    "LK_JWT_IMAGE": {"Entrypoint": None, "Cmd": ["/lk-jwt-service"]},
    "CONTROLPLANE_IMAGE": {"Entrypoint": None, "Cmd": ["/registration"]},
    "CASHIER_IMAGE": {"Entrypoint": ["/cashier"], "Cmd": None},
}


def check(condition: object, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def parse_manifest(lines: list[str]) -> dict[str, str]:
    check(len(lines) == len(IMAGE_KEYS), lines)
    values: dict[str, str] = {}
    for expected_key, line in zip(IMAGE_KEYS, lines):
        check(line and line == line.strip() and not line.startswith("#"), line)
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([^\s]+)", line)
        check(match and match.group(1) == expected_key and expected_key not in values, line)
        values[expected_key] = match.group(2)
    for key, (repository, pattern) in IMAGE_RULES.items():
        image_repository, separator, tag = values[key].rpartition(":")
        check(separator and image_repository == repository and re.fullmatch(pattern, tag), (key, values[key]))
        check("@" not in values[key] and "latest" not in tag.lower(), (key, values[key]))
    return values


def load_manifest(path: Path) -> dict[str, str]:
    values = json.loads(path.read_text(encoding="utf-8"))
    check(type(values) is dict and set(values) == set(IMAGE_KEYS), "selected image set")
    return parse_manifest([f"{key}={values[key]}" for key in IMAGE_KEYS])


def github_api(endpoint: str, key: str) -> dict:
    environment = dict(os.environ)
    if key == "CASHIER_IMAGE":
        token = environment.get("CASHIER_RELEASE_TOKEN")
        check(token, "CASHIER_RELEASE_TOKEN is required for the private Cashier release")
        environment["GH_TOKEN"] = token
    result = subprocess.run(["gh", "api", "--hostname", "github.com", endpoint],
                            env=environment, stdout=subprocess.PIPE, check=True, text=True, timeout=60)
    return json.loads(result.stdout)


def release_tag(source_commit: str, run_id: str, attempt: str) -> str:
    check(re.fullmatch(r"[0-9a-f]{40}", source_commit), "release source commit")
    check(re.fullmatch(r"[1-9][0-9]*", run_id) and re.fullmatch(r"[1-9][0-9]*", attempt), "release run identity")
    return f"server-state-{source_commit[:8]}-{run_id}-{attempt}"


def resolve_releases(directory: Path) -> dict[str, str]:
    """Resolve GitHub's stable release once; downstream jobs consume these files."""
    directory.mkdir(parents=True, exist_ok=True)
    values = {}
    for key in IMAGE_KEYS:
        if key in PRODUCT_RELEASES:
            repository = PRODUCT_RELEASES[key]["repository"]
        else:
            repository = UPSTREAM_RELEASES[key]
        release = github_api(f"repos/{repository}/releases/latest", key)
        check(isinstance(release, dict) and release.get("draft") is False
              and release.get("prerelease") is False and release.get("published_at"),
              (key, "latest published stable release required"))
        tag = release.get("tag_name")
        check(isinstance(tag, str), (key, "release tag"))
        if key in PRODUCT_RELEASES:
            check(release.get("immutable") is True, (key, "immutable product release required"))
            image_tag = tag
        else:
            image_tag = tag.removeprefix("v") + ("-alpine" if key == "CADDY_IMAGE" else "")
        values[key] = f"{IMAGE_RULES[key][0]}:{image_tag}"
        (directory / f"{key}.release.json").write_text(json.dumps(release), encoding="utf-8")
    values = parse_manifest([f"{key}={values[key]}" for key in IMAGE_KEYS])
    (directory / "selection.json").write_text(json.dumps(values) + "\n", encoding="utf-8")
    return values


def image_reference_filename(image: str) -> str:
    check(re.fullmatch(r"[^:@\s]+:[^:@\s]+", image), image)
    return image.translate(str.maketrans("/:", "__"))


def config_parts(document: object) -> dict:
    check(isinstance(document, dict), "OCI config object")
    config = document.get("config", document)
    check(isinstance(config, dict), "OCI config section")
    return config


def _metadata_name(repository: str) -> set[str]:
    names = {repository}
    if repository.startswith("docker.io/") and repository.count("/") == 1:
        names.add(repository.replace("docker.io/", "docker.io/library/", 1))
    return names


def validate_image_platform(metadata: object, config_document: object) -> None:
    check(isinstance(metadata, dict) and metadata.get("Os") == "linux" and metadata.get("Architecture") == "amd64", "linux/amd64 metadata selection")
    check(isinstance(config_document, dict) and config_document.get("os") == "linux" and config_document.get("architecture") == "amd64", "linux/amd64 config selection")


def validate_synapse_provenance(inspect_labels: object, config_labels: object, version: str) -> None:
    expected = {"org.opencontainers.image.source": "https://github.com/TeleCrypt-io/synapse-server", "org.opencontainers.image.version": version, "org.opencontainers.image.base.name": "ghcr.io/element-hq/synapse"}
    for labels in (inspect_labels, config_labels):
        check(isinstance(labels, dict), "Synapse labels")
        check(set(SYNAPSE_LABELS) <= set(labels), "complete Synapse provenance")
        check(all(type(labels[label]) is str for label in SYNAPSE_LABELS), "Synapse label types")
        for label, value in expected.items():
            check(labels.get(label) == value, (label, labels.get(label)))
        check(re.fullmatch(r"[0-9a-f]{40}", labels.get("org.opencontainers.image.revision", "")), "Synapse revision")
        # The Synapse release selects its embedded wheel independently of the Go services image.
        check(re.fullmatch(IMAGE_RULES["CONTROLPLANE_IMAGE"][1], labels.get("org.telecrypt.controlplane.release", "")), "embedded Controlplane release")
        check(re.fullmatch(r"v?\d+\.\d+\.\d+", labels.get("org.opencontainers.image.base.version", "")), "Synapse base version")
        check(re.fullmatch(r"v?\d+\.\d+\.\d+", labels.get("org.telecrypt.s3-provider.version", "")), "S3 provider version")
        for label in ("org.telecrypt.controlplane.wheel.sha256", "org.telecrypt.s3-provider.fork.archive.sha256"):
            check(re.fullmatch(r"[0-9a-f]{64}", labels.get(label, "")), label)
    check(all(inspect_labels[label] == config_labels[label] for label in SYNAPSE_LABELS), "Synapse metadata channel mismatch")


def validate_published_images(directory: Path) -> None:
    values = load_manifest(directory / "selection.json")
    images = {}
    for key in IMAGE_KEYS:
        name = image_reference_filename(values[key])
        labels = json.loads((directory / f"{name}.labels").read_text(encoding="utf-8"))
        config_document = json.loads((directory / f"{name}.config").read_text(encoding="utf-8"))
        config = config_parts(config_document)
        metadata = json.loads((directory / f"{name}.metadata").read_text(encoding="utf-8"))
        repository = values[key].rsplit(":", 1)[0]
        check(type(metadata) is dict and type(metadata.get("Name")) is str and type(metadata.get("Digest")) is str, (key, "metadata fields"))
        check(metadata["Name"] in _metadata_name(repository), (key, "repository"))
        validate_image_platform(metadata, config_document)
        check(re.fullmatch(r"sha256:[0-9a-f]{64}", metadata["Digest"]), (key, "digest"))
        for field, expected in IMAGE_CONFIG.get(key, {}).items():
            check(config.get(field) == expected, (key, field, config.get(field)))
        images[key] = (labels, config, metadata)
    for key in ("CONTROLPLANE_IMAGE", "CASHIER_IMAGE"):
        labels, config, _ = images[key]
        version = values[key].rsplit(":", 1)[1]
        config_labels = config.get("Labels")
        for channel in (labels, config_labels):
            check(type(channel) is dict, (key, "labels"))
            check(all(type(channel.get(label)) is str for label in (
                "org.opencontainers.image.source", "org.opencontainers.image.version",
                "org.opencontainers.image.revision", "io.telecrypt.config-contract",
            )), (key, "label types"))
            check(channel.get("org.opencontainers.image.source") == f"https://github.com/TeleCrypt-io/{'control-plane' if key == 'CONTROLPLANE_IMAGE' else 'cashier'}", (key, "source"))
            check(channel.get("org.opencontainers.image.version") == version, (key, "version"))
            check(re.fullmatch(r"[0-9a-f]{40}", channel.get("org.opencontainers.image.revision", "")), (key, "revision"))
            check(channel.get("io.telecrypt.config-contract") == "1", (key, "config contract"))
        check(labels["org.opencontainers.image.revision"] == config_labels["org.opencontainers.image.revision"], (key, "label channels"))
        if key == "CASHIER_IMAGE":
            check(validate_cashier_provenance(labels, values[key]) == validate_cashier_provenance(config_labels, values[key]), (key, "label channels"))
        check(config.get("User") == "991:991", (key, "user"))
    labels, config, _ = images["SYNAPSE_IMAGE"]
    validate_synapse_provenance(
        labels,
        config.get("Labels"),
        values["SYNAPSE_IMAGE"].rsplit(":", 1)[1],
    )
    print("Verified published image repositories, digests, config, and provenance labels")


def product_release_asset_name(key: str, image: str) -> str:
    return f"{PRODUCT_RELEASES[key]['asset_prefix']}{image.rsplit(':', 1)[1]}.digest.json"


def validate_cashier_provenance(labels: object, image: str) -> dict[str, str]:
    version = image.rsplit(":", 1)[1]
    check(type(labels) is dict, ("CASHIER_IMAGE", "provenance labels"))
    source = labels.get("org.opencontainers.image.source")
    label_version = labels.get("org.opencontainers.image.version")
    revision = labels.get("org.opencontainers.image.revision")
    check(
        type(source) is str
        and source == "https://github.com/TeleCrypt-io/cashier"
        and type(label_version) is str
        and label_version == version
        and type(revision) is str
        and re.fullmatch(r"[0-9a-f]{40}", revision),
        ("CASHIER_IMAGE", "provenance"),
    )
    return {"source": source, "version": label_version, "revision": revision}


def validate_image_record(key: str, record: object) -> None:
    check(type(record) is dict and set(record) == IMAGE_RECORD_KEYS, (key, "record shape"))


def product_release_asset_names(key: str, image: str) -> set[str]:
    tag = image.rsplit(":", 1)[1]
    names = {product_release_asset_name(key, image)}
    if key == "CONTROLPLANE_IMAGE":
        names.add(f"telecrypt_tier_controller-{tag}-py3-none-any.whl")
    return names


def parse_product_release_asset(key: str, raw: bytes) -> dict[str, str]:
    check(key in PRODUCT_RELEASE_KEYS, (key, "public release evidence"))
    try:
        text = raw.decode("utf-8")
        values = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError((key, "release asset JSON")) from error
    check(type(values) is dict and json.dumps(values, sort_keys=True, separators=(",", ":")) + "\n" == text, (key, "canonical asset"))
    fields = {"annotated_tag_sha", "digest", "image", "schema_version", "source_commit", "tag"}
    check(set(values) == fields and type(values["schema_version"]) is int and values["schema_version"] == 1, (key, "asset schema"))
    for field in fields - {"schema_version"}:
        check(type(values[field]) is str, (key, field, "asset field type"))
    return {"image": values["image"], "tag": values["tag"], "commit": values["source_commit"], "annotated_tag_sha": values["annotated_tag_sha"], "digest": values["digest"]}


def product_release_body(key: str, tag: str, source_commit: str) -> str:
    check(key in PRODUCT_RELEASE_KEYS, (key, "public release evidence"))
    if key == "CONTROLPLANE_IMAGE":
        return f"Exact Controlplane release {tag}."
    if key == "SYNAPSE_IMAGE":
        return f"Exact Synapse release for source commit {source_commit}."
    if key == "CASHIER_IMAGE":
        return f"Exact Cashier release for source commit {source_commit}."
    return "TeleCrypt immutable image digest record."


def validate_release_asset_label(key: str, item: object) -> str:
    check(type(item) is dict and type(item.get("label")) is str and item["label"] == "", (key, "asset label"))
    return item["label"]


def validate_product_tag_evidence(
    key: str,
    tag: str,
    source_commit: str,
    annotated_tag_sha: str,
    tag_ref_document: dict,
    annotated_tag_document: dict,
) -> None:
    api_root = f"https://api.github.com/repos/{PRODUCT_RELEASES[key]['repository']}"
    check(
        type(tag_ref_document) is dict
        and tag_ref_document.get("ref") == f"refs/tags/{tag}",
        (key, "tag ref"),
    )
    check(
        tag_ref_document.get("url") == f"{api_root}/git/refs/tags/{tag}",
        (key, "tag ref URL"),
    )
    ref_object = tag_ref_document.get("object")
    check(
        type(ref_object) is dict
        and ref_object.get("type") == "tag"
        and ref_object.get("sha") == annotated_tag_sha,
        (key, "annotated tag ref object"),
    )
    check(
        ref_object.get("url") == f"{api_root}/git/tags/{annotated_tag_sha}",
        (key, "annotated tag ref object URL"),
    )
    check(
        type(annotated_tag_document) is dict
        and annotated_tag_document.get("sha") == annotated_tag_sha
        and annotated_tag_document.get("tag") == tag,
        (key, "annotated tag object"),
    )
    check(
        annotated_tag_document.get("url") == f"{api_root}/git/tags/{annotated_tag_sha}",
        (key, "annotated tag object URL"),
    )
    peeled = annotated_tag_document.get("object")
    check(
        type(peeled) is dict
        and peeled.get("type") == "commit"
        and peeled.get("sha") == source_commit,
        (key, "peeled tag commit"),
    )
    check(
        peeled.get("url") == f"{api_root}/git/commits/{source_commit}",
        (key, "peeled tag commit URL"),
    )


def validate_product_release(
    key: str,
    image: str,
    expected_digest: str,
    labels: dict,
    release_document: dict,
    asset: bytes,
    tag_ref_document: dict,
    annotated_tag_document: dict,
) -> dict[str, object]:
    tag = image.rsplit(":", 1)[1]
    expected_asset = product_release_asset_name(key, image)
    check(isinstance(release_document, dict), (key, "release object"))
    release_id = release_document.get("id")
    check(type(release_id) is int and release_id > 0, (key, "release id"))
    check(
        release_document.get("tag_name") == tag
        and release_document.get("name") == tag
        and release_document.get("draft") is False
        and release_document.get("prerelease") is False
        and release_document.get("immutable") is True,
        (key, "release identity/state"),
    )
    release_body_value = release_document.get("body")
    check(type(release_body_value) is str, (key, "release body type"))
    check(
        release_body_value == product_release_body(key, tag, labels.get("org.opencontainers.image.revision", "")),
        (key, "release body"),
    )
    assets = release_document.get("assets")
    expected_assets = product_release_asset_names(key, image)
    check(type(assets) is list and len(assets) == len(expected_assets), (key, "asset set"))
    asset_names = [item.get("name") if type(item) is dict else None for item in assets]
    check(all(type(name) is str for name in asset_names) and set(asset_names) == expected_assets, (key, "asset set"))
    seen_ids: set[int] = set()
    for item in assets:
        check(type(item) is dict and type(item.get("id")) is int and item["id"] > 0 and item["id"] not in seen_ids, (key, "asset id"))
        seen_ids.add(item["id"])
        validate_release_asset_label(key, item)
        name = item.get("name")
        check(
            type(name) is str
            and item.get("state") == "uploaded"
            and type(item.get("size")) is int
            and item["size"] > 0
            and item["size"] <= 64 * 1024 * 1024,
            (key, name, "asset state/size"),
        )
        check(
            type(item.get("digest")) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"]),
            (key, name, "asset digest"),
        )
    selected = next(item for item in assets if item.get("name") == expected_asset)
    check(selected["size"] <= 1048576 and len(asset) == selected["size"] and "sha256:" + hashlib.sha256(asset).hexdigest() == selected["digest"], (key, "asset bytes"))
    payload = parse_product_release_asset(key, asset)
    check(payload["image"] == image.rsplit(":", 1)[0] and payload["tag"] == tag and re.fullmatch(r"[0-9a-f]{40}", payload["commit"]) and payload["commit"] == labels.get("org.opencontainers.image.revision") and payload["digest"] == expected_digest, (key, "asset binding"))
    check(re.fullmatch(r"[0-9a-f]{40}", payload["annotated_tag_sha"]), (key, "annotated tag"))
    validate_product_tag_evidence(key, tag, payload["commit"], payload["annotated_tag_sha"], tag_ref_document, annotated_tag_document)
    return {
        "asset": expected_asset,
        "asset_id": selected["id"],
        "asset_label": selected["label"],
        "asset_digest": selected["digest"],
        "asset_size": selected["size"],
        "release_id": release_id,
        "source_commit": payload["commit"],
        "tag": tag,
        "annotated_tag_sha": payload["annotated_tag_sha"],
        "body": release_body_value,
    }


def image_release_manifest(values: dict[str, str], metadata: dict[str, dict], labels: dict[str, dict], release_tag: str, source_commit: str, annotated_tag_sha: str, product_releases: dict[str, dict] | None = None, product_assets: dict[str, bytes] | None = None, product_tag_refs: dict[str, dict] | None = None, product_annotated_tags: dict[str, dict] | None = None, resolved_digests: dict[str, str] | None = None) -> dict:
    check(re.fullmatch(r"server-state-[0-9a-f]{7,10}-[1-9][0-9]*-[1-9][0-9]*", release_tag) and re.fullmatch(r"[0-9a-f]{40}", source_commit) and re.fullmatch(r"[0-9a-f]{40}", annotated_tag_sha), "outer release identity")
    check(source_commit.startswith(release_tag.split("-")[2]), "release source prefix")
    records = {}
    for key in IMAGE_KEYS:
        image = values[key]
        repository = image.rsplit(":", 1)[0]
        document = metadata[key]
        check(type(document) is dict and type(document.get("Name")) is str and type(document.get("Digest")) is str and document["Name"] in _metadata_name(repository) and re.fullmatch(r"sha256:[0-9a-f]{64}", document["Digest"]), (key, "image metadata"))
        digest = resolved_digests.get(key, document["Digest"]) if resolved_digests else document["Digest"]
        check(re.fullmatch(r"sha256:[0-9a-f]{64}", digest), (key, "resolved digest"))
        record = {"digest": digest, "image": image}
        if key in PRODUCT_RELEASE_KEYS:
            check(product_releases and product_assets and product_tag_refs and product_annotated_tags and key in product_releases and key in product_assets and key in product_tag_refs and key in product_annotated_tags, (key, "release evidence"))
            provenance = labels[key]
            check(type(provenance) is dict, (key, "provenance labels"))
            expected_source = f"https://github.com/{PRODUCT_RELEASES[key]['repository']}"
            check(
                type(provenance.get("org.opencontainers.image.source")) is str
                and provenance["org.opencontainers.image.source"] == expected_source
                and type(provenance.get("org.opencontainers.image.version")) is str
                and provenance["org.opencontainers.image.version"] == image.rsplit(":", 1)[1],
                (key, "provenance"),
            )
            release_record = validate_product_release(
                key,
                image,
                digest,
                provenance,
                product_releases[key],
                product_assets[key],
                product_tag_refs[key],
                product_annotated_tags[key],
            )
            check(set(release_record) == PRODUCT_RELEASE_RECORD_KEYS, (key, "release record shape"))
            check(release_record["source_commit"] == provenance.get("org.opencontainers.image.revision"), (key, "release revision"))
        elif key == "CASHIER_IMAGE":
            validate_cashier_provenance(labels[key], image)
        validate_image_record(key, record)
        records[key] = record
    check(set(records) == set(IMAGE_KEYS), "expected image manifest")
    return {"annotated_tag_sha": annotated_tag_sha, "images": records, "schema_version": 1, "server_state_tag": release_tag, "source_commit": source_commit}


def validate_image_release_manifest(directory: Path, output: Path, release_tag: str, source_commit: str, annotated_tag_sha: str) -> None:
    values = load_manifest(directory / "selection.json")
    validate_published_images(directory)
    metadata = {key: json.loads((directory / f"{image_reference_filename(values[key])}.metadata").read_text(encoding="utf-8")) for key in IMAGE_KEYS}
    labels = {key: json.loads((directory / f"{image_reference_filename(values[key])}.labels").read_text(encoding="utf-8")) for key in IMAGE_KEYS}
    releases = {key: json.loads((directory / f"{key}.release.json").read_text(encoding="utf-8")) for key in PRODUCT_RELEASES}
    assets = {key: (directory / f"{key}.release.asset").read_bytes() for key in PRODUCT_RELEASES}
    tag_refs = {key: json.loads((directory / f"{key}.annotated-tag-ref.json").read_text(encoding="utf-8")) for key in PRODUCT_RELEASES}
    annotated_tags = {key: json.loads((directory / f"{key}.annotated-tag.json").read_text(encoding="utf-8")) for key in PRODUCT_RELEASES}
    resolved_digests = {
        key: (directory / f"{key}.tag-digest").read_text(encoding="utf-8").strip()
        for key in IMAGE_KEYS
    }
    check(all(re.fullmatch(r"sha256:[0-9a-f]{64}", digest) for digest in resolved_digests.values()), "resolved tag digests")
    document = image_release_manifest(values, metadata, labels, release_tag, source_commit, annotated_tag_sha, releases, assets, tag_refs, annotated_tags, resolved_digests)
    output.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote deterministic image release manifest: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("resolve", "manifest", "image-release-manifest", "image-name", "selection-env", "product-inputs"))
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("value", nargs="?")
    parser.add_argument("output", nargs="?", type=Path)
    args = parser.parse_args()
    check(args.path is not None, "input path required")
    if args.command == "resolve":
        resolve_releases(args.path)
    elif args.command in ("manifest", "selection-env", "product-inputs"):
        values = load_manifest(args.path / "selection.json")
        if args.command == "selection-env":
            for key, image in values.items():
                print(f"{key}={image}")
        elif args.command == "product-inputs":
            for key, product in PRODUCT_RELEASES.items():
                print(key, values[key], product["repository"], product_release_asset_name(key, values[key]))
        else:
            print("Verified resolved image selection")
    elif args.command == "image-release-manifest":
        check(args.value and args.output and args.path.is_dir(), "image metadata directory, release tag, and output required")
        source_commit = os.environ.get("GITHUB_SHA", "")
        annotated_tag_sha = os.environ.get("SERVER_STATE_ANNOTATED_TAG_SHA", "")
        check(source_commit and annotated_tag_sha, "release identity environment")
        validate_image_release_manifest(args.path, args.output, args.value, source_commit, annotated_tag_sha)
    else:
        print(image_reference_filename(str(args.path)))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"Server State contract failure: {error}", file=sys.stderr)
        raise SystemExit(1)
