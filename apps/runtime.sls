{% set data_dir = '/home/ubuntu/salt_config' %}
{% set secrets_dir = data_dir ~ '/secrets' %}
{% set secret_names = (
  'janitor.secrets.env',
  'plan.secrets.env',
  'cashier.secrets.env',
  'cashier-plan-token.env',
  'cashier-synapse-token.env',
  'cashier-janitor-token.env',
  'cashier-dodo-webhook-secret.env'
) %}

apps-data-directory:
  file.directory:
    - name: {{ data_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - require:
      - user: salt-operator

apps-secrets-directory:
  file.directory:
    - name: {{ secrets_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - require:
      - file: apps-data-directory

# Podman reads its standard host auth file when Quadlet pulls the private Cashier image.
# Keep this credential on the host; it is not mounted into application containers.
apps-registry-auth:
  file.managed:
    - name: /home/ubuntu/.config/containers/auth.json
    - source: salt://hosts/{{ grains['id'] }}/secrets/ghcr.auth.json
    - user: ubuntu
    - group: ubuntu
    - mode: '0600'
    - show_changes: false
    - require:
      - file: salt-operator-containers-directory

{% for name in secret_names %}
apps-secret-{{ name|replace('.', '-') }}:
  file.managed:
    - name: {{ secrets_dir }}/{{ name }}
    - source: salt://hosts/{{ grains['id'] }}/secrets/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0600'
    - show_changes: false
    - require:
      - file: apps-secrets-directory
{% endfor %}
