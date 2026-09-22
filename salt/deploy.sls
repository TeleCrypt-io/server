{#
  Activate one release after the master has selected its file root. The image
  manifest is read from Salt's file server and is never resolved on the VM.
#}
{% set vars = pillar["telecrypt"] %}
{% set release = vars["release"] %}
{% set tag = release["tag"] %}
{% set data_dir = "/home/ubuntu/salt_config" %}
{% set uid = salt["user.info"]("ubuntu").get("uid", 1000)|int %}
{% set env = {
  "HOME": "/home/ubuntu",
  "XDG_RUNTIME_DIR": "/run/user/" ~ uid|string,
  "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/" ~ uid|string ~ "/bus"
} %}
{% set manifest_text = salt["cp.get_file_str"]("salt://server-state-images.json") %}
{% set manifest = salt["slsutil.deserialize"]("json", manifest_text) %}
{% if manifest.get("schema_version") != 1 %}
  {{ salt["test.raise_exception"]("ValueError", "server-state-images.json schema_version must be 1") }}
{% endif %}
{% if manifest.get("server_state_tag") != tag %}
  {{ salt["test.raise_exception"]("ValueError", "server-state-images.json does not match the selected release tag") }}
{% endif %}
{% set images = manifest.get("images", {}) %}
{% set image_keys = ("CADDY_IMAGE", "SYNAPSE_IMAGE", "MAS_IMAGE", "CONTROLPLANE_IMAGE", "CASHIER_IMAGE", "LK_JWT_IMAGE") %}
{% if images.keys()|list|sort != image_keys|list|sort %}
  {{ salt["test.raise_exception"]("ValueError", "server-state-images.json must contain exactly the six application images") }}
{% endif %}
{% for key in image_keys %}
  {% if images[key].get("image", "") is not string or images[key].get("digest", "") is not string or not images[key]["digest"].startswith("sha256:") %}
    {{ salt["test.raise_exception"]("ValueError", "server-state-images.json contains an invalid image entry") }}
  {% endif %}
{% endfor %}
{% set image_versions = {} %}
{% set image_digests = {} %}
{% for key in image_keys %}
  {% set _ = image_versions.update({key: images[key]["image"]}) %}
  {% set _ = image_digests.update({key: images[key]["digest"]}) %}
{% endfor %}
{% set activation = {
  "status": "pending",
  "server_name": vars["server"]["name"],
  "billing_environment": vars["server"]["billing_environment"],
  "release": tag,
  "commit": manifest["source_commit"],
  "annotated_tag_sha": manifest["annotated_tag_sha"],
  "image_versions": image_versions,
  "image_digests": image_digests
} %}

include:
  - salt.release

{% for key in image_keys %}
telecrypt-pull-{{ key|lower|replace("_", "-") }}:
  cmd.run:
    - name: /usr/bin/podman pull {{ images[key]["image"] }}@{{ images[key]["digest"] }}
    - unless: /usr/bin/podman image exists {{ images[key]["image"] }}@{{ images[key]["digest"] }}
    - runas: ubuntu
    - env: {{ env }}
    - require:
      - file: telecrypt-current-release
{% endfor %}

telecrypt-image-environment:
  file.managed:
    - name: {{ data_dir }}/telecrypt-images.env
    - contents: |
{% for key in image_keys %}
        {{ key }}={{ images[key]["image"] }}@{{ images[key]["digest"] }}
{% endfor %}
    - user: ubuntu
    - group: ubuntu
    - mode: '0600'
    - show_changes: false
    - require:
{% for key in image_keys %}
      - cmd: telecrypt-pull-{{ key|lower|replace("_", "-") }}
{% endfor %}

telecrypt-activation-pending:
  file.serialize:
    - name: {{ data_dir }}/deploy-state/activation.json
    - serializer: json
    - dataset: {{ activation | tojson }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0600'
    - show_changes: false
    - unless: >-
        /usr/bin/python3 -c 'import json,sys;
        d=json.load(open(sys.argv[1], encoding="utf-8"));
        sys.exit(0 if d.get("status") == "succeeded" and d.get("release") == sys.argv[2] else 1)'
        {{ data_dir }}/deploy-state/activation.json {{ tag }}
    - require:
      - file: telecrypt-image-environment

telecrypt-activate-stack:
  cmd.run:
    - name: >-
        if /usr/bin/systemctl --user daemon-reload &&
           /usr/bin/systemctl --user start telecrypt-pod.service &&
           /usr/bin/systemctl --user restart
           telecrypt-mas.service
           telecrypt-lk-jwt.service
           telecrypt-synapse.service
           telecrypt-registration.service
           telecrypt-plan.service
           telecrypt-cashier.service
           telecrypt-caddy.service &&
           /usr/bin/systemctl --user start telecrypt.target; then
          exit 0
        else
          status=$?
          /usr/bin/python3 -c 'import json,os,sys;
          p=sys.argv[1]; d=json.load(open(p, encoding="utf-8")); d["status"]="failed";
          t=p+".tmp"; f=open(t, "w", encoding="utf-8"); json.dump(d, f, sort_keys=True); f.write("\\n"); f.close(); os.chmod(t, 0o600); os.replace(t, p)'
          {{ data_dir }}/deploy-state/activation.json
          exit "$status"
        fi
    - runas: ubuntu
    - env: {{ env }}
    - shell: /bin/bash
    - unless: >-
        /usr/bin/python3 -c 'import json,sys;
        d=json.load(open(sys.argv[1], encoding="utf-8"));
        sys.exit(0 if d.get("status") == "succeeded" and d.get("release") == sys.argv[2] else 1)'
        {{ data_dir }}/deploy-state/activation.json {{ tag }}
    - require:
      - file: telecrypt-activation-pending

telecrypt-activation:
  cmd.run:
    - name: >-
        /usr/bin/python3 -c 'import json,os,sys;
        p=sys.argv[1]; d=json.load(open(p, encoding="utf-8")); d["status"]="succeeded";
        t=p+".tmp"; f=open(t, "w", encoding="utf-8"); json.dump(d, f, sort_keys=True); f.write("\\n"); f.close(); os.chmod(t, 0o600); os.replace(t, p)'
        {{ data_dir }}/deploy-state/activation.json
    - runas: ubuntu
    - env: {{ env }}
    - shell: /bin/bash
    - unless: >-
        /usr/bin/python3 -c 'import json,sys;
        d=json.load(open(sys.argv[1], encoding="utf-8"));
        sys.exit(0 if d.get("status") == "succeeded" and d.get("release") == sys.argv[2] else 1)'
        {{ data_dir }}/deploy-state/activation.json {{ tag }}
    - require:
      - cmd: telecrypt-activate-stack
