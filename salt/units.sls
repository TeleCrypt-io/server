{% set data_dir = "/home/ubuntu/salt_config" %}
{% set release_tag = pillar["telecrypt"]["release"]["tag"] %}
{% set release_dir = data_dir ~ "/releases/" ~ release_tag %}
{% set unit_dir = "/home/ubuntu/.config/systemd/user" %}
{% set quadlet_dir = "/home/ubuntu/.config/containers/systemd" %}
{% set service_units = (
  "telecrypt-pod.service",
  "telecrypt.target",
  "telecrypt-janitor.service",
  "telecrypt-janitor.timer"
) %}
{% set quadlet_units = (
  "telecrypt-caddy.container",
  "telecrypt-cashier.container",
  "telecrypt-lk-jwt.container",
  "telecrypt-mas.container",
  "telecrypt-plan.container",
  "telecrypt-registration.container",
  "telecrypt-synapse.container"
) %}

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

{% for name in service_units %}
telecrypt-migrate-unit-{{ name|replace(".", "-") }}:
  cmd.run:
    - name: >-
        /usr/bin/cp --remove-destination --preserve=mode,ownership
        {{ release_dir }}/systemd/{{ name }} {{ unit_dir }}/{{ name }}
    - onlyif: /usr/bin/test -L {{ unit_dir }}/{{ name }}
    - require:
      - file: telecrypt-user-unit-directory
      - file: telecrypt-current-release

telecrypt-unit-{{ name|replace(".", "-") }}:
  file.managed:
    - name: {{ unit_dir }}/{{ name }}
    - source: {{ release_dir }}/systemd/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - force: true
    - follow_symlinks: false
    - require:
      - file: telecrypt-user-unit-directory
      - file: telecrypt-current-release
      - cmd: telecrypt-migrate-unit-{{ name|replace(".", "-") }}
{% endfor %}

{% for name in quadlet_units %}
telecrypt-migrate-quadlet-{{ name|replace(".", "-") }}:
  cmd.run:
    - name: >-
        /usr/bin/cp --remove-destination --preserve=mode,ownership
        {{ release_dir }}/systemd/quadlet/{{ name }} {{ quadlet_dir }}/{{ name }}
    - onlyif: /usr/bin/test -L {{ quadlet_dir }}/{{ name }}
    - require:
      - file: telecrypt-quadlet-directory
      - file: telecrypt-current-release

telecrypt-quadlet-{{ name|replace(".", "-") }}:
  file.managed:
    - name: {{ quadlet_dir }}/{{ name }}
    - source: {{ release_dir }}/systemd/quadlet/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - force: true
    - follow_symlinks: false
    - require:
      - file: telecrypt-quadlet-directory
      - file: telecrypt-current-release
      - cmd: telecrypt-migrate-quadlet-{{ name|replace(".", "-") }}
{% endfor %}

telecrypt-user-daemon-reload:
  cmd.run:
    - name: systemctl --user daemon-reload
    - runas: ubuntu
    - env:
        HOME: /home/ubuntu
        XDG_RUNTIME_DIR: /run/user/{{ salt["user.info"]("ubuntu").get("uid", 1000)|int }}
        DBUS_SESSION_BUS_ADDRESS: unix:path=/run/user/{{ salt["user.info"]("ubuntu").get("uid", 1000)|int }}/bus
    - require:
      - file: telecrypt-user-unit-directory
      - file: telecrypt-quadlet-directory
{% for name in service_units %}
      - file: telecrypt-unit-{{ name|replace(".", "-") }}
{% endfor %}
{% for name in quadlet_units %}
      - file: telecrypt-quadlet-{{ name|replace(".", "-") }}
{% endfor %}
