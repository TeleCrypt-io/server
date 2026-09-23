{#
  Activate one release after the master has selected its file root. The image
  manifest is read from Salt's file server and is never resolved on the VM.
#}
{% set vars = pillar["telecrypt"] %}
{% set release = vars["release"] %}
{% set tag = release["tag"] %}
{% set data_dir = "/home/ubuntu/salt_config" %}
{% set image_env_dir = data_dir ~ "/image-env" %}
{% set marker = "/run/user/" ~ salt["user.info"]("ubuntu").get("uid", 1000)|int ~ "/telecrypt-pod-refreshed" %}
{% set uid = salt["user.info"]("ubuntu").get("uid", 1000)|int %}
{% set pod_pid = "/run/user/" ~ uid ~ "/telecrypt-pod.pid" %}
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
  - salt.runtime
  - salt.units

telecrypt-activation-pending:
  file.serialize:
    - name: {{ data_dir }}/deploy-state/activation.json
    - serializer: json
    - dataset: {{ activation | tojson }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0600'
    - show_changes: false
    - order: 1
    - unless: >-
        /usr/bin/python3 -c 'import json,sys;
        d=json.load(open(sys.argv[1], encoding="utf-8"));
        sys.exit(0 if d.get("status") == "succeeded" and d.get("release") == sys.argv[2] else 1)'
        {{ data_dir }}/deploy-state/activation.json {{ tag }}
    - require:
      - file: telecrypt-current-release
      - file: telecrypt-deploy-state-directory

{% for key in image_keys %}
telecrypt-pull-{{ key|lower|replace("_", "-") }}:
  cmd.run:
    - name: /usr/bin/podman pull {{ images[key]["image"] }}@{{ images[key]["digest"] }}
    - unless: /usr/bin/podman image exists {{ images[key]["image"] }}@{{ images[key]["digest"] }}
    - runas: ubuntu
    - env: {{ env }}
    - require:
      - file: telecrypt-activation-pending
      - file: telecrypt-current-release
{% endfor %}

{% for key in image_keys %}
telecrypt-image-env-{{ key|lower|replace("_", "-") }}:
  file.managed:
    - name: {{ image_env_dir }}/{{ key|lower|replace("_", "-") }}.env
    - contents: {{ key }}={{ images[key]["image"] }}@{{ images[key]["digest"] }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0600'
    - show_changes: false
    - require:
      - file: telecrypt-image-environment-directory
      - cmd: telecrypt-pull-{{ key|lower|replace("_", "-") }}
{% endfor %}

telecrypt-clear-pod-refresh-marker:
  cmd.run:
    - name: /usr/bin/rm -f {{ marker }}
    - runas: ubuntu
    - env: {{ env }}
    - unless: /usr/bin/test ! -e {{ marker }}
    - require:
      - file: telecrypt-activation-pending

telecrypt-pod-refresh:
  cmd.run:
    - name: |
        if /usr/bin/systemctl --user is-active --quiet telecrypt-pod.service; then
          /usr/bin/systemctl --user restart telecrypt-pod.service
          /usr/bin/touch {{ marker }}
        fi
    - runas: ubuntu
    - env: {{ env }}
    - shell: /bin/bash
    - onchanges:
      - file: telecrypt-unit-telecrypt-pod-service
      - file: telecrypt-unit-telecrypt-target
      - file: telecrypt-deployment-environment
      - cmd: telecrypt-migrate-unit-telecrypt-pod-service
      - cmd: telecrypt-migrate-unit-telecrypt-target
    - require:
      - file: telecrypt-activation-pending
      - cmd: telecrypt-clear-pod-refresh-marker
      - cmd: telecrypt-user-daemon-reload
      - file: telecrypt-unit-telecrypt-pod-service
      - file: telecrypt-unit-telecrypt-target
      - file: telecrypt-deployment-environment

telecrypt-pod-recover:
  cmd.run:
    - name: |
        /usr/bin/systemctl --user restart telecrypt-pod.service
        /usr/bin/touch {{ marker }}
    - runas: ubuntu
    - env: {{ env }}
    - shell: /bin/bash
    - onlyif: >-
        /usr/bin/test ! -s {{ pod_pid }}
        && /usr/bin/systemctl --user is-active --quiet telecrypt-pod.service
    - unless: /usr/bin/test -e {{ marker }}
    - require:
      - file: telecrypt-activation-pending
      - cmd: telecrypt-clear-pod-refresh-marker
      - cmd: telecrypt-user-daemon-reload

{% set service_triggers = {
  "caddy": (
    "telecrypt-quadlet-telecrypt-caddy-container",
    "telecrypt-image-env-caddy-image",
    "telecrypt-caddy-config",
    "telecrypt-secret-dodo-webhook-env"
  ),
  "cashier": (
    "telecrypt-quadlet-telecrypt-cashier-container",
    "telecrypt-image-env-cashier-image",
    "telecrypt-secret-cashier-secrets-env",
    "telecrypt-secret-cashier-plan-token-env",
    "telecrypt-secret-cashier-synapse-token-env",
    "telecrypt-secret-cashier-janitor-token-env",
    "telecrypt-secret-dodo-webhook-env",
    "telecrypt-secret-cashier-dodo-webhook-secret-env"
  ),
  "lk-jwt": (
    "telecrypt-quadlet-telecrypt-lk-jwt-container",
    "telecrypt-image-env-lk-jwt-image",
    "telecrypt-secret-livekit-secrets-env"
  ),
  "mas": (
    "telecrypt-quadlet-telecrypt-mas-container",
    "telecrypt-image-env-mas-image",
    "telecrypt-mas-config",
    "telecrypt-mas-runtime",
    "telecrypt-mas-environment",
    "telecrypt-secret-mas-secrets-json"
  ),
  "plan": (
    "telecrypt-quadlet-telecrypt-plan-container",
    "telecrypt-image-env-controlplane-image",
    "telecrypt-secret-plan-secrets-env",
    "telecrypt-secret-cashier-plan-token-env"
  ),
  "registration": (
    "telecrypt-quadlet-telecrypt-registration-container",
    "telecrypt-image-env-controlplane-image"
  ),
  "synapse": (
    "telecrypt-quadlet-telecrypt-synapse-container",
    "telecrypt-image-env-synapse-image",
    "telecrypt-synapse-config",
    "telecrypt-synapse-runtime",
    "telecrypt-synapse-log-config",
    "telecrypt-secret-cashier-synapse-token-env",
    "telecrypt-secret-synapse-secrets-json",
    "telecrypt-secret-synapse-signing-key"
  )
} %}
{% set service_migration_triggers = {
  "caddy": ("telecrypt-migrate-quadlet-telecrypt-caddy-container",),
  "cashier": ("telecrypt-migrate-quadlet-telecrypt-cashier-container",),
  "lk-jwt": ("telecrypt-migrate-quadlet-telecrypt-lk-jwt-container",),
  "mas": ("telecrypt-migrate-quadlet-telecrypt-mas-container",),
  "plan": ("telecrypt-migrate-quadlet-telecrypt-plan-container",),
  "registration": ("telecrypt-migrate-quadlet-telecrypt-registration-container",),
  "synapse": ("telecrypt-migrate-quadlet-telecrypt-synapse-container",)
} %}

{% for service, triggers in service_triggers.items() %}
telecrypt-refresh-{{ service }}:
  cmd.run:
    - name: /usr/bin/systemctl --user try-restart telecrypt-{{ service }}.service
    - runas: ubuntu
    - env: {{ env }}
    - unless: /usr/bin/test -e {{ marker }}
    - onchanges:
{% for trigger in triggers %}
      - file: {{ trigger }}
{% endfor %}
{% for trigger in service_migration_triggers[service] %}
      - cmd: {{ trigger }}
{% endfor %}
    - require:
      - file: telecrypt-activation-pending
      - cmd: telecrypt-clear-pod-refresh-marker
      - cmd: telecrypt-user-daemon-reload
{% for trigger in triggers %}
      - file: {{ trigger }}
{% endfor %}
{% for trigger in service_migration_triggers[service] %}
      - cmd: {{ trigger }}
{% endfor %}
{% endfor %}

telecrypt-refresh-janitor-timer:
  cmd.run:
    - name: /usr/bin/systemctl --user restart telecrypt-janitor.timer
    - runas: ubuntu
    - env: {{ env }}
    - onchanges:
      - file: telecrypt-unit-telecrypt-janitor-timer
    - require:
      - cmd: telecrypt-user-daemon-reload
      - file: telecrypt-unit-telecrypt-janitor-timer

telecrypt-start-stack:
  cmd.run:
    - name: >-
        /usr/bin/systemctl --user start telecrypt.target telecrypt-pod.service
        telecrypt-caddy.service telecrypt-mas.service telecrypt-synapse.service
        telecrypt-registration.service telecrypt-plan.service telecrypt-cashier.service
        telecrypt-lk-jwt.service
    - runas: ubuntu
    - env: {{ env }}
    - require:
      - file: telecrypt-activation-pending
      - cmd: telecrypt-user-daemon-reload
      - cmd: telecrypt-pod-refresh
      - cmd: telecrypt-pod-recover
      - cmd: telecrypt-refresh-janitor-timer
{% for service in service_triggers %}
      - cmd: telecrypt-refresh-{{ service }}
{% endfor %}
{% for key in image_keys %}
      - file: telecrypt-image-env-{{ key|lower|replace("_", "-") }}
{% endfor %}
      - file: telecrypt-secret-janitor-secrets-env
      - file: telecrypt-deploy-state-directory

telecrypt-activation-failed:
  cmd.run:
    - name: >-
        /usr/bin/python3 -c 'import json,os,sys;
        p=sys.argv[1]; expected=sys.argv[2];
        d=json.load(open(p, encoding="utf-8"));
        d.__setitem__("status", "failed") if d.get("release") == expected else None;
        t=p+".tmp";
        f=open(t, "w", encoding="utf-8");
        json.dump(d, f, sort_keys=True); f.write("\n"); f.close();
        os.chmod(t, 0o600); os.replace(t, p)' {{ data_dir }}/deploy-state/activation.json {{ tag }}
    - runas: ubuntu
    - env: {{ env }}
    - shell: /bin/bash
    - onfail:
      - cmd: telecrypt-start-stack

telecrypt-activation:
  cmd.run:
    - name: >-
        /usr/bin/python3 -c 'import json,os,sys;
        p=sys.argv[1]; d=json.load(open(p, encoding="utf-8"));
        d["status"]="succeeded";
        t=p+".tmp";
        f=open(t, "w", encoding="utf-8");
        json.dump(d, f, sort_keys=True); f.write("\n"); f.close();
        os.chmod(t, 0o600); os.replace(t, p)' {{ data_dir }}/deploy-state/activation.json
    - runas: ubuntu
    - env: {{ env }}
    - shell: /bin/bash
    - unless: >-
        /usr/bin/python3 -c 'import json,sys;
        d=json.load(open(sys.argv[1], encoding="utf-8"));
        sys.exit(0 if d.get("status") == "succeeded" and d.get("release") == sys.argv[2] else 1)'
        {{ data_dir }}/deploy-state/activation.json {{ tag }}
    - require:
      - cmd: telecrypt-start-stack
