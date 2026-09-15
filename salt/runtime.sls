{% set t = pillar["telecrypt"] %}
{% set data_dir = t["data_dir"] %}
{% set runtime_dir = data_dir ~ "/runtime" %}
{% set secrets_dir = data_dir ~ "/secrets" %}
{% set deploy_state_dir = data_dir ~ "/deploy-state" %}

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
    - source: salt://salt/templates/deployment.env.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0600'
    - show_changes: false
    - require:
      - user: telecrypt-operator

telecrypt-synapse-runtime-identity:
  file.managed:
    - name: {{ runtime_dir }}/synapse.identity.yaml
    - source: salt://salt/templates/synapse.identity.yaml.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - show_changes: false
    - require:
      - file: telecrypt-runtime-directory

telecrypt-mas-runtime-identity:
  file.managed:
    - name: {{ runtime_dir }}/mas.identity.yaml
    - source: salt://salt/templates/mas.identity.yaml.j2
    - template: jinja
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
