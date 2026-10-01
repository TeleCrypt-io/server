{% set quadlet_dir = '/home/ubuntu/.config/containers/systemd' %}
{% set unit_dir = '/home/ubuntu/.config/systemd/user' %}
{% set cashier_inputs = (
  'apps-secret-cashier-secrets-env',
  'apps-secret-cashier-plan-token-env',
  'apps-secret-cashier-synapse-token-env',
  'apps-secret-cashier-janitor-token-env',
  'apps-secret-cashier-dodo-webhook-secret-env'
) %}
{% set plan_inputs = ('apps-secret-plan-secrets-env', 'apps-secret-cashier-plan-token-env') %}
{% set janitor_inputs = ('apps-secret-janitor-secrets-env', 'apps-secret-cashier-janitor-token-env') %}
{% set janitor_dependency_inputs = (
  'apps-pod-quadlet',
  'apps-cashier-quadlet'
) + cashier_inputs + (
  'apps-plan-quadlet',
) + plan_inputs + janitor_inputs %}

apps-quadlet-directory:
  file.directory:
    - name: {{ quadlet_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - makedirs: true
    - require:
      - user: salt-operator

apps-user-unit-directory:
  file.directory:
    - name: {{ unit_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - makedirs: true
    - require:
      - user: salt-operator

apps-pod-quiescent:
  user_service.dead:
    - name: apps-pod.service
    - user: ubuntu
    - timeout: 900
    - prereq:
      - file: apps-pod-quadlet
    - require:
      - service: salt-user-manager

apps-pod-quadlet:
  file.managed:
    - name: {{ quadlet_dir }}/apps.pod
    - source: salt://apps/quadlet/apps.pod.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - require:
      - file: apps-quadlet-directory

{% for name, inputs in (
  ('cashier', cashier_inputs),
  ('plan', plan_inputs),
  ('registration', ()),
) %}
apps-{{ name }}-quiescent:
  user_service.dead:
    - name: {{ name }}.service
    - user: ubuntu
    - timeout: 900
    - prereq:
      - file: apps-{{ name }}-quadlet
{% for input_state in inputs %}
      - file: {{ input_state }}
{% endfor %}
    - require:
      - service: salt-user-manager

apps-{{ name }}-quadlet:
  file.managed:
    - name: {{ quadlet_dir }}/{{ name }}.container
    - source: salt://apps/quadlet/{{ name }}.container.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - require:
      - file: apps-quadlet-directory
      - file: apps-pod-quadlet
{% endfor %}

apps-janitor-quiescent:
  user_service.dead:
    - name: janitor.service
    - user: ubuntu
    - timeout: 900
    - prereq:
      - file: apps-janitor-quadlet
{% for input_state in janitor_dependency_inputs %}
      - file: {{ input_state }}
{% endfor %}
    - require:
      - service: salt-user-manager

apps-janitor-quadlet:
  file.managed:
    - name: {{ quadlet_dir }}/janitor.container
    - source: salt://apps/quadlet/janitor.container.j2
    - template: jinja
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - require:
      - file: apps-quadlet-directory
      - file: apps-pod-quadlet

apps-janitor-timer-quiescent:
  user_service.dead:
    - name: janitor.timer
    - user: ubuntu
    - prereq:
      - file: apps-janitor-timer
      - file: apps-janitor-quadlet
{% for input_state in janitor_dependency_inputs %}
      - file: {{ input_state }}
{% endfor %}
    - require:
      - service: salt-user-manager

apps-janitor-timer:
  file.managed:
    - name: {{ unit_dir }}/janitor.timer
    - source: salt://apps/quadlet/janitor.timer
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - require:
      - file: apps-user-unit-directory

apps-janitor-timer-enabled:
  file.symlink:
    - name: {{ unit_dir }}/timers.target.wants/janitor.timer
    - target: {{ unit_dir }}/janitor.timer
    - makedirs: true
    - user: ubuntu
    - group: ubuntu
    - require:
      - file: apps-janitor-timer
