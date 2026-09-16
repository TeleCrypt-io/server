#!/usr/bin/env python3
"""Validate selected Server State images and their published evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMAGE_KEYS = (
    "CADDY_IMAGE",
    "SYNAPSE_IMAGE",
    "MAS_IMAGE",
    "CONTROLPLANE_IMAGE",
    "CASHIER_IMAGE",
    "LK_JWT_IMAGE",
)
IMAGE_REPOSITORIES = {
    "CADDY_IMAGE": "docker.io/caddy",
    "SYNAPSE_IMAGE": "ghcr.io/telecrypt-io/telecrypt-synapse",
    "MAS_IMAGE": "ghcr.io/element-hq/matrix-authentication-service",
    "CONTROLPLANE_IMAGE": "ghcr.io/telecrypt-io/controlplane",
    "CASHIER_IMAGE": "ghcr.io/telecrypt-io/telecrypt-cashier",
    "LK_JWT_IMAGE": "ghcr.io/element-hq/lk-jwt-service",
}
IMAGE_REFERENCE = re.compile(
    r"^(?P<repository>[a-z0-9]+(?:[._/-][a-z0-9]+)*):"
    r"(?P<tag>[A-Za-z0-9][A-Za-z0-9._-]{0,127})$"
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
SERVER_STATE_TAG = re.compile(r"^server-state-[0-9a-f]{7,10}-[1-9][0-9]*$")
PUBLIC_RELEASES = {
    "SYNAPSE_IMAGE": {"repository": "TeleCrypt-io/synapse-server", "asset_prefix": "telecrypt-synapse-"},
    "CONTROLPLANE_IMAGE": {"repository": "TeleCrypt-io/control-plane", "asset_prefix": "controlplane-"},
}
PUBLIC_RELEASE_KEYS = frozenset(PUBLIC_RELEASES)
IMAGE_RECORD_KEYS = frozenset({"digest", "image"})
PRODUCT_RELEASE_RECORD_KEYS = {
    "asset", "asset_id", "asset_digest", "asset_size", "release_id",
    "source_commit", "tag", "annotated_tag_sha",
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


def _image_parts(image: str, key: str | None = None) -> tuple[str, str]:
    match = IMAGE_REFERENCE.fullmatch(image)
    check(match is not None, image)
    repository, tag = match.group("repository"), match.group("tag")
    if key is not None:
        check(repository == IMAGE_REPOSITORIES[key], (key, image))
    return repository, tag


def parse_manifest(lines: list[str]) -> dict[str, str]:
    check(len(lines) == len(IMAGE_KEYS), lines)
    values: dict[str, str] = {}
    for expected_key, line in zip(IMAGE_KEYS, lines):
        check(line and line == line.strip() and not line.startswith("#"), line)
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([^\s]+)", line)
        check(match and match.group(1) == expected_key and expected_key not in values, line)
        values[expected_key] = match.group(2)
    for key, image in values.items():
        _image_parts(image, key)
    return values


def load_manifest(values: dict[str, str] | None = None) -> dict[str, str]:
    if values is None:
        values = {key: os.environ.get(key, "") for key in IMAGE_KEYS}
    return parse_manifest([f"{key}={values[key]}" for key in IMAGE_KEYS])


def image_reference_filename(image: str) -> str:
    _image_parts(image)
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
    expected = {
        "org.opencontainers.image.source": "https://github.com/TeleCrypt-io/synapse-server",
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.base.name": "ghcr.io/element-hq/synapse",
    }
    for labels in (inspect_labels, config_labels):
        check(isinstance(labels, dict), "Synapse labels")
        check(set(SYNAPSE_LABELS) <= set(labels), "complete Synapse provenance")
        check(all(type(labels[label]) is str for label in SYNAPSE_LABELS), "Synapse label types")
        for label, value in expected.items():
            check(labels.get(label) == value, (label, labels.get(label)))
        check(HEX40.fullmatch(labels.get("org.opencontainers.image.revision", "")), "Synapse revision")
        check(re.fullmatch(r"v?\d+\.\d+\.\d+", labels.get("org.telecrypt.controlplane.release", "")), "embedded Controlplane release")
        check(re.fullmatch(r"v?\d+\.\d+\.\d+", labels.get("org.opencontainers.image.base.version", "")), "Synapse base version")
        check(re.fullmatch(r"v?\d+\.\d+\.\d+", labels.get("org.telecrypt.s3-provider.version", "")), "S3 provider version")
        for label in ("org.telecrypt.controlplane.wheel.sha256", "org.telecrypt.s3-provider.fork.archive.sha256"):
            check(re.fullmatch(r"[0-9a-f]{64}", labels.get(label, "")), label)
    check(all(inspect_labels[label] == config_labels[label] for label in SYNAPSE_LABELS), "Synapse metadata channel mismatch")


def validate_cashier_provenance(labels: object, image: str) -> dict[str, str]:
    _, version = _image_parts(image, "CASHIER_IMAGE")
    check(type(labels) is dict, ("CASHIER_IMAGE", "provenance labels"))
    source = labels.get("org.opencontainers.image.source")
    label_version = labels.get("org.opencontainers.image.version")
    revision = labels.get("org.opencontainers.image.revision")
    check(
        source == "https://github.com/TeleCrypt-io/cashier"
        and label_version == version
        and isinstance(revision, str)
        and HEX40.fullmatch(revision),
        ("CASHIER_IMAGE", "provenance"),
    )
    return {"source": source, "version": label_version, "revision": revision}


def validate_published_images(directory: Path, values: dict[str, str] | None = None) -> None:
    values = load_manifest(values)
    images = {}
    for key in IMAGE_KEYS:
        name = image_reference_filename(values[key])
        labels = json.loads((directory / f"{name}.labels").read_text(encoding="utf-8"))
        config_document = json.loads((directory / f"{name}.config").read_text(encoding="utf-8"))
        config = config_parts(config_document)
        metadata = json.loads((directory / f"{name}.metadata").read_text(encoding="utf-8"))
        repository, _ = _image_parts(values[key], key)
        check(type(metadata) is dict and type(metadata.get("Name")) is str and type(metadata.get("Digest")) is str, (key, "metadata fields"))
        check(metadata["Name"] in _metadata_name(repository), (key, "repository"))
        validate_image_platform(metadata, config_document)
        check(SHA256.fullmatch(metadata["Digest"]), (key, "digest"))
        for field, expected in IMAGE_CONFIG.get(key, {}).items():
            check(config.get(field) == expected, (key, field, config.get(field)))
        images[key] = (labels, config, metadata)
    for key in ("CONTROLPLANE_IMAGE", "CASHIER_IMAGE"):
        labels, config, _ = images[key]
        _, version = _image_parts(values[key], key)
        config_labels = config.get("Labels")
        for channel in (labels, config_labels):
            check(type(channel) is dict, (key, "labels"))
            check(all(type(channel.get(label)) is str for label in (
                "org.opencontainers.image.source", "org.opencontainers.image.version",
                "org.opencontainers.image.revision", "io.telecrypt.config-contract",
            )), (key, "label types"))
            check(channel.get("org.opencontainers.image.source") == f"https://github.com/TeleCrypt-io/{'control-plane' if key == 'CONTROLPLANE_IMAGE' else 'cashier'}", (key, "source"))
            check(channel.get("org.opencontainers.image.version") == version, (key, "version"))
            check(HEX40.fullmatch(channel.get("org.opencontainers.image.revision", "")), (key, "revision"))
            check(channel.get("io.telecrypt.config-contract") == "1", (key, "config contract"))
        check(labels["org.opencontainers.image.revision"] == config_labels["org.opencontainers.image.revision"], (key, "label channels"))
        if key == "CASHIER_IMAGE":
            check(validate_cashier_provenance(labels, values[key]) == validate_cashier_provenance(config_labels, values[key]), (key, "label channels"))
        check(config.get("User") == "991:991", (key, "user"))
    labels, config, _ = images["SYNAPSE_IMAGE"]
    _, version = _image_parts(values["SYNAPSE_IMAGE"], "SYNAPSE_IMAGE")
    validate_synapse_provenance(labels, config.get("Labels"), version)
    print("Verified published image repositories, digests, config, and provenance labels")


def product_release_asset_name(key: str, image: str) -> str:
    _, tag = _image_parts(image, key)
    return f"{PUBLIC_RELEASES[key]['asset_prefix']}{tag}.digest.json"


def parse_product_release_asset(key: str, raw: bytes) -> dict[str, str]:
    check(key in PUBLIC_RELEASE_KEYS, (key, "public release evidence"))
    try:
        values = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError((key, "release asset JSON")) from error
    fields = {"annotated_tag_sha", "digest", "image", "schema_version", "source_commit", "tag"}
    check(type(values) is dict and fields <= set(values) and values.get("schema_version") == 1, (key, "asset schema"))
    for field in fields - {"schema_version"}:
        check(type(values[field]) is str, (key, field, "asset field type"))
    check(HEX40.fullmatch(values["annotated_tag_sha"]) and HEX40.fullmatch(values["source_commit"]), (key, "asset identity"))
    check(SHA256.fullmatch(values["digest"]), (key, "asset digest"))
    return {
        "image": values["image"], "tag": values["tag"], "commit": values["source_commit"],
        "annotated_tag_sha": values["annotated_tag_sha"], "digest": values["digest"],
    }


def validate_product_tag_evidence(
    key: str,
    tag: str,
    source_commit: str,
    annotated_tag_sha: str,
    tag_ref_document: dict,
    annotated_tag_document: dict,
) -> None:
    check(type(tag_ref_document) is dict and tag_ref_document.get("ref") == f"refs/tags/{tag}", (key, "tag ref"))
    ref_object = tag_ref_document.get("object")
    check(type(ref_object) is dict and ref_object.get("type") == "tag" and ref_object.get("sha") == annotated_tag_sha, (key, "annotated tag ref object"))
    check(
        type(annotated_tag_document) is dict
        and annotated_tag_document.get("sha") == annotated_tag_sha
        and annotated_tag_document.get("tag") == tag,
        (key, "annotated tag object"),
    )
    peeled = annotated_tag_document.get("object")
    check(type(peeled) is dict and peeled.get("type") == "commit" and peeled.get("sha") == source_commit, (key, "peeled tag commit"))


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
    _, tag = _image_parts(image, key)
    expected_asset = product_release_asset_name(key, image)
    check(isinstance(release_document, dict), (key, "release object"))
    release_id = release_document.get("id")
    check(type(release_id) is int and release_id > 0, (key, "release id"))
    check(
        release_document.get("tag_name") == tag
        and release_document.get("draft") is False
        and release_document.get("prerelease") is False
        and release_document.get("immutable") is True,
        (key, "release identity/state"),
    )
    assets = release_document.get("assets")
    check(isinstance(assets, list), (key, "assets"))
    matches = [item for item in assets if isinstance(item, dict) and item.get("name") == expected_asset]
    check(len(matches) == 1, (key, "selected asset"))
    selected = matches[0]
    check(
        selected.get("state") == "uploaded"
        and type(selected.get("id")) is int
        and selected["id"] > 0
        and type(selected.get("size")) is int
        and selected["size"] > 0
        and isinstance(selected.get("digest"), str)
        and SHA256.fullmatch(selected["digest"]),
        (key, "selected asset metadata"),
    )
    check(len(asset) == selected["size"] and "sha256:" + hashlib.sha256(asset).hexdigest() == selected["digest"], (key, "asset bytes"))
    payload = parse_product_release_asset(key, asset)
    repository, _ = _image_parts(image, key)
    check(
        payload["image"] == repository
        and payload["tag"] == tag
        and payload["commit"] == labels.get("org.opencontainers.image.revision")
        and payload["digest"] == expected_digest,
        (key, "asset binding"),
    )
    validate_product_tag_evidence(key, tag, payload["commit"], payload["annotated_tag_sha"], tag_ref_document, annotated_tag_document)
    return {
        "asset": expected_asset,
        "asset_id": selected["id"],
        "asset_digest": selected["digest"],
        "asset_size": selected["size"],
        "release_id": release_id,
        "source_commit": payload["commit"],
        "tag": tag,
        "annotated_tag_sha": payload["annotated_tag_sha"],
    }


def validate_image_record(key: str, record: object) -> None:
    check(type(record) is dict and set(record) == IMAGE_RECORD_KEYS, (key, "record shape"))


def image_release_manifest(
    values: dict[str, str],
    metadata: dict[str, dict],
    labels: dict[str, dict],
    release_tag: str,
    source_commit: str,
    annotated_tag_sha: str,
    product_releases: dict[str, dict] | None = None,
    product_assets: dict[str, bytes] | None = None,
    product_tag_refs: dict[str, dict] | None = None,
    product_annotated_tags: dict[str, dict] | None = None,
    resolved_digests: dict[str, str] | None = None,
) -> dict:
    check(SERVER_STATE_TAG.fullmatch(release_tag) and HEX40.fullmatch(source_commit) and HEX40.fullmatch(annotated_tag_sha), "outer release identity")
    values = load_manifest(values)
    records = {}
    for key in IMAGE_KEYS:
        image = values[key]
        repository, version = _image_parts(image, key)
        document = metadata[key]
        check(type(document) is dict and type(document.get("Name")) is str and type(document.get("Digest")) is str and document["Name"] in _metadata_name(repository) and SHA256.fullmatch(document["Digest"]), (key, "image metadata"))
        digest = resolved_digests.get(key, document["Digest"]) if resolved_digests else document["Digest"]
        check(SHA256.fullmatch(digest), (key, "resolved digest"))
        record = {"digest": digest, "image": image}
        if key in PUBLIC_RELEASE_KEYS:
            check(product_releases and product_assets and product_tag_refs and product_annotated_tags and key in product_releases and key in product_assets and key in product_tag_refs and key in product_annotated_tags, (key, "release evidence"))
            provenance = labels[key]
            check(type(provenance) is dict and provenance.get("org.opencontainers.image.source") == f"https://github.com/TeleCrypt-io/{'synapse-server' if key == 'SYNAPSE_IMAGE' else 'control-plane'}" and provenance.get("org.opencontainers.image.version") == version, (key, "provenance"))
            release_record = validate_product_release(key, image, digest, provenance, product_releases[key], product_assets[key], product_tag_refs[key], product_annotated_tags[key])
            check(set(release_record) == PRODUCT_RELEASE_RECORD_KEYS, (key, "release record shape"))
            check(release_record["source_commit"] == provenance.get("org.opencontainers.image.revision"), (key, "release revision"))
        elif key == "CASHIER_IMAGE":
            validate_cashier_provenance(labels[key], image)
        validate_image_record(key, record)
        records[key] = record
    check(set(records) == set(IMAGE_KEYS), "six-image manifest")
    return {"annotated_tag_sha": annotated_tag_sha, "images": records, "schema_version": 1, "server_state_tag": release_tag, "source_commit": source_commit}


def validate_image_release_manifest(directory: Path, output: Path, release_tag: str, source_commit: str, annotated_tag_sha: str, values: dict[str, str] | None = None) -> None:
    values = load_manifest(values)
    validate_published_images(directory, values)
    metadata = {key: json.loads((directory / f"{image_reference_filename(values[key])}.metadata").read_text(encoding="utf-8")) for key in IMAGE_KEYS}
    labels = {key: json.loads((directory / f"{image_reference_filename(values[key])}.labels").read_text(encoding="utf-8")) for key in IMAGE_KEYS}
    releases = {key: json.loads((directory / f"{key}.release.json").read_text(encoding="utf-8")) for key in PUBLIC_RELEASES}
    assets = {key: (directory / f"{key}.release.asset").read_bytes() for key in PUBLIC_RELEASES}
    tag_refs = {key: json.loads((directory / f"{key}.annotated-tag-ref.json").read_text(encoding="utf-8")) for key in PUBLIC_RELEASES}
    annotated_tags = {key: json.loads((directory / f"{key}.annotated-tag.json").read_text(encoding="utf-8")) for key in PUBLIC_RELEASES}
    resolved_digests = {key: (directory / f"{key}.tag-digest").read_text(encoding="utf-8").strip() for key in IMAGE_KEYS}
    check(all(SHA256.fullmatch(digest) for digest in resolved_digests.values()), "resolved tag digests")
    document = image_release_manifest(values, metadata, labels, release_tag, source_commit, annotated_tag_sha, releases, assets, tag_refs, annotated_tags, resolved_digests)
    output.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote deterministic image release manifest: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("manifest", "image-release-manifest", "image-name"))
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("value", nargs="?")
    parser.add_argument("output", nargs="?", type=Path)
    args = parser.parse_args()
    if args.command == "image-name":
        check(args.path is not None, "image coordinate required")
        print(image_reference_filename(str(args.path)))
        return
    values = load_manifest()
    if args.command == "manifest":
        print("Verified exact six-image selected image inputs")
    else:
        check(args.path and args.value and args.output and args.path.is_dir(), "image metadata directory, release tag, and output required")
        source_commit = os.environ.get("GITHUB_SHA", "")
        annotated_tag_sha = os.environ.get("SERVER_STATE_ANNOTATED_TAG_SHA", "")
        check(source_commit and annotated_tag_sha, "release identity environment")
        validate_image_release_manifest(args.path, args.output, args.value, source_commit, annotated_tag_sha, values)


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"Server State contract failure: {error}", file=os.sys.stderr)
        raise SystemExit(1)
