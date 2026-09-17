{% set data_dir = "/home/ubuntu/salt_config" %}
{% set unit_dir = "/home/ubuntu/.config/systemd/user" %}
{% set quadlet_dir = "/home/ubuntu/.config/containers/systemd" %}

telecrypt-user-unit-directory:
  file.directory:
    - name: {{ unit_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - makedirs: true

telecrypt-quadlet-directory:
  file.directory:
    - name: {{ quadlet_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0775'
    - makedirs: true

{% for name in ("telecrypt-pod.service", "telecrypt.target", "telecrypt-janitor.service") %}
telecrypt-unit-link-{{ name|replace(".", "-") }}:
  file.symlink:
    - name: {{ unit_dir }}/{{ name }}
    - target: {{ data_dir }}/current/systemd/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - force: true
    - atomic: true
    - require:
      - file: telecrypt-user-unit-directory
{% endfor %}

{% for name in ("telecrypt-caddy.container", "telecrypt-cashier.container", "telecrypt-lk-jwt.container", "telecrypt-mas.container", "telecrypt-plan.container", "telecrypt-registration.container", "telecrypt-synapse.container") %}
telecrypt-quadlet-link-{{ name|replace(".", "-") }}:
  file.symlink:
    - name: {{ quadlet_dir }}/{{ name }}
    - target: {{ data_dir }}/current/systemd/quadlet/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - force: true
    - atomic: true
    - require:
      - file: telecrypt-quadlet-directory
{% endfor %}
