#!/usr/bin/env python3
"""Start the released SFU configuration and exercise its authenticated room API."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import jinja2


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    key, secret = "check", secrets.token_hex(32)
    config = jinja2.Environment().from_string(Path("livekit.yaml.j2").read_text()).render(
        pillar={"telecrypt": {"livekit": {"public_ip": "192.0.2.1", "api_key": key}}}
    )
    (root / "config.yaml").write_text(config)
    keys = root / "keys.yaml"
    keys.write_text(f"{key}: {secret}\n")
    keys.chmod(0o400)
    run("podman", "unshare", "chown", "991:991", str(keys))
    container = run(
        "podman", "create", "--user=991:991", "--read-only",
        "--cap-drop=ALL", "--cap-add=NET_BIND_SERVICE", "--security-opt=no-new-privileges",
        "-p", "127.0.0.1::7880", "-v", f"{root}/config.yaml:/etc/livekit/config.yaml:ro",
        "-v", f"{keys}:/etc/livekit/keys.yaml:ro", sys.argv[1],
        "--config", "/etc/livekit/config.yaml",
    )
    try:
        run("podman", "start", container)
        address = "http://" + run("podman", "port", container, "7880/tcp")
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(address, timeout=1) as response:
                    assert response.status == 200
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        claims = {"iss": key, "exp": int(time.time()) + 60,
                  "video": {"roomCreate": True, "roomList": True, "roomAdmin": True, "room": "release-check"}}
        payload = b64(b'{"alg":"HS256","typ":"JWT"}') + "." + b64(json.dumps(claims).encode())
        token = payload + "." + b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        def call(method, body, authorized=True):
            headers = {"Content-Type": "application/json"}
            if authorized:
                headers["Authorization"] = "Bearer " + token
            request = urllib.request.Request(address + "/twirp/livekit.RoomService/" + method,
                                             data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.load(response)
        try:
            call("ListRooms", {}, authorized=False)
            raise AssertionError("Unauthenticated RoomService unexpectedly succeeded")
        except urllib.error.HTTPError as error:
            assert error.code == 401, error.code
        room = call("CreateRoom", {"name": "release-check"})
        assert room["name"] == "release-check", room
        call("DeleteRoom", {"room": "release-check"})
        print("LiveKit private-key startup and authenticated room create/delete passed")
    except BaseException:
        subprocess.run(["podman", "logs", container], check=False)
        raise
    finally:
        run("podman", "rm", "-f", "--time=0", container)
