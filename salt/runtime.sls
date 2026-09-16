{% set t = pillar["telecrypt"] %}
{% set data_dir = t["data_dir"] %}
{% set runtime_dir = data_dir ~ "/runtime" %}
{% set secrets_dir = data_dir ~ "/secrets" %}
{% set deploy_state_dir = data_dir ~ "/deploy-state" %}
{% set mas_rust_log = t["mas_rust_log"] %}

telecrypt-data-directory:
  file.directory:
    - name: {{ data_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - makedirs: true
    - require:
      - user: telecrypt-operator

telecrypt-runtime-directory:
  file.directory:
    - name: {{ runtime_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - require:
      - file: telecrypt-data-directory

telecrypt-secrets-directory:
  file.directory:
    - name: {{ secrets_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - require:
      - file: telecrypt-data-directory

telecrypt-deploy-state-directory:
  file.directory:
    - name: {{ deploy_state_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - require:
      - file: telecrypt-data-directory

telecrypt-synapse-staging-directory:
  file.directory:
    - name: {{ runtime_dir }}/synapse-staging
    - user: {{ t["subuid_start"]|int + 990 }}
    - group: {{ t["subgid_start"]|int + 990 }}
    - mode: '0711'
    - makedirs: true
    - require:
      - file: telecrypt-runtime-directory

telecrypt-synapse-staging-tmp-directory:
  file.directory:
    - name: {{ runtime_dir }}/synapse-staging/tmp
    - user: {{ t["subuid_start"]|int + 990 }}
    - group: {{ t["subgid_start"]|int + 990 }}
    - mode: '0700'
    - require:
      - file: telecrypt-synapse-staging-directory

telecrypt-deployment-environment:
  file.managed:
    - name: /home/ubuntu/telecrypt-deployment.env
    - contents: |
        TELECRYPT_DATA_DIR={{ t["data_dir"] }}
        SERVER_NAME={{ t["server_name"] }}
        BILLING_ENVIRONMENT={{ t["billing_environment"] }}
        INGRESS_BIND_ADDRESS={{ t["ingress_bind_address"] }}
        TRUSTED_PROXY={{ t["trusted_proxy"] }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0600'
    - show_changes: false
    - require:
      - user: telecrypt-operator

telecrypt-synapse-runtime:
  file.managed:
    - name: {{ runtime_dir }}/synapse.runtime.yaml
    - source: salt://matrix/synapse.runtime.yaml.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory

telecrypt-synapse-log-config:
  file.managed:
    - name: {{ runtime_dir }}/synapse.log.config
    - source: salt://matrix/synapse.log.config.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory

telecrypt-mas-runtime:
  file.managed:
    - name: {{ runtime_dir }}/mas.runtime.yaml
    - source: salt://matrix/mas.runtime.yaml.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory

telecrypt-mas-environment:
  file.managed:
    - name: {{ runtime_dir }}/mas.environment
    - contents: |
        RUST_LOG={{ mas_rust_log }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory

{% for name, mode in (
  ("janitor.secrets.env", "0600"),
  ("plan.secrets.env", "0600"),
  ("cashier.secrets.env", "0600"),
  ("dodo-webhook.env", "0600"),
  ("livekit.secrets.env", "0600"),
  ("synapse.secrets.json", "0444"),
  ("synapse_signing.key", "0444"),
  ("mas.secrets.json", "0444")
) %}
telecrypt-secret-metadata-{{ name|replace(".", "-")|replace("_", "-") }}:
  file.managed:
    - name: {{ secrets_dir }}/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - mode: '{{ mode }}'
    - replace: false
    - create: false
    - show_changes: false
    - require:
      - file: telecrypt-secrets-directory
{% endfor %}
