{% set vars = pillar["telecrypt"] %}
{% set server = vars["server"] %}
{% set operator = vars["operator"] %}
{% set mas = vars["mas"] %}
{% set data_dir = "/home/ubuntu/salt_config" %}
{% set release_dir = data_dir ~ "/releases/" ~ vars["release"]["tag"] %}
{% set runtime_dir = data_dir ~ "/runtime" %}
{% set secrets_dir = data_dir ~ "/secrets" %}
{% set image_env_dir = data_dir ~ "/image-env" %}
{% set deploy_state_dir = data_dir ~ "/deploy-state" %}
{% set mas_rust_log = mas["rust_log"] %}

telecrypt-data-directory:
  file.directory:
    - name: {{ data_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - makedirs: true

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

telecrypt-image-environment-directory:
  file.directory:
    - name: {{ image_env_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - makedirs: true
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
    - user: {{ operator["subuid_start"]|int + 990 }}
    - group: {{ operator["subgid_start"]|int + 990 }}
    - mode: '0711'
    - makedirs: true
    - require:
      - file: telecrypt-runtime-directory

telecrypt-synapse-staging-tmp-directory:
  file.directory:
    - name: {{ runtime_dir }}/synapse-staging/tmp
    - user: {{ operator["subuid_start"]|int + 990 }}
    - group: {{ operator["subgid_start"]|int + 990 }}
    - mode: '0700'
    - require:
      - file: telecrypt-synapse-staging-directory

telecrypt-deployment-environment:
  file.managed:
    - name: {{ data_dir }}/telecrypt-deployment.env
    - contents: |
        TELECRYPT_DATA_DIR={{ data_dir }}
        SERVER_NAME={{ server["name"] }}
        BILLING_ENVIRONMENT={{ server["billing_environment"] }}
        INGRESS_BIND_ADDRESS={{ server["ingress_bind_address"] }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0600'
    - show_changes: false

telecrypt-synapse-runtime:
  file.managed:
    - name: {{ runtime_dir }}/synapse.runtime.yaml
    - source: {{ release_dir }}/matrix/synapse.runtime.yaml.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory
      - file: telecrypt-current-release

telecrypt-caddy-config:
  file.managed:
    - name: {{ runtime_dir }}/Caddyfile
    - source: {{ release_dir }}/Caddyfile
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory
      - file: telecrypt-current-release

telecrypt-synapse-config:
  file.managed:
    - name: {{ runtime_dir }}/synapse.yaml
    - source: {{ release_dir }}/matrix/synapse.yaml
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory
      - file: telecrypt-current-release

telecrypt-mas-config:
  file.managed:
    - name: {{ runtime_dir }}/mas.yaml
    - source: {{ release_dir }}/matrix/mas.yaml
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory
      - file: telecrypt-current-release

telecrypt-synapse-log-config:
  file.managed:
    - name: {{ runtime_dir }}/synapse.log.config
    - source: {{ release_dir }}/matrix/synapse.log.config.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory
      - file: telecrypt-current-release

telecrypt-mas-runtime:
  file.managed:
    - name: {{ runtime_dir }}/mas.runtime.yaml
    - source: {{ release_dir }}/matrix/mas.runtime.yaml.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory
      - file: telecrypt-current-release

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
  ("cashier-plan-token.env", "0600"),
  ("cashier-synapse-token.env", "0600"),
  ("cashier-janitor-token.env", "0600"),
  ("dodo-webhook.env", "0600"),
  ("livekit.secrets.env", "0600"),
  ("synapse.secrets.json", "0444"),
  ("synapse_signing.key", "0444"),
  ("mas.secrets.json", "0444")
) %}
telecrypt-secret-{{ name|replace(".", "-")|replace("_", "-") }}:
  file.managed:
    - name: {{ secrets_dir }}/{{ name }}
    - contents_pillar: secrets:{{ name }}
    - user: ubuntu
    - group: ubuntu
    - mode: '{{ mode }}'
    - show_changes: false
    - require:
      - file: telecrypt-secrets-directory
{% endfor %}
