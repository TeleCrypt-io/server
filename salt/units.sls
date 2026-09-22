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
telecrypt-unit-{{ name|replace(".", "-") }}:
  file.managed:
    - name: {{ unit_dir }}/{{ name }}
    - source: salt://systemd/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - force: true
    - require:
      - file: telecrypt-user-unit-directory
{% endfor %}

{% for name in quadlet_units %}
telecrypt-quadlet-{{ name|replace(".", "-") }}:
  file.managed:
    - name: {{ quadlet_dir }}/{{ name }}
    - source: salt://systemd/quadlet/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - force: true
    - require:
      - file: telecrypt-quadlet-directory
{% endfor %}

telecrypt-user-daemon-reload:
  cmd.run:
    - name: systemctl --user daemon-reload
    - runas: ubuntu
    - env:
        HOME: /home/ubuntu
        XDG_RUNTIME_DIR: /run/user/{{ salt["user.info"]("ubuntu").get("uid", 1000)|int }}
        DBUS_SESSION_BUS_ADDRESS: unix:path=/run/user/{{ salt["user.info"]("ubuntu").get("uid", 1000)|int }}/bus
    - onchanges:
{% for name in service_units %}
      - file: telecrypt-unit-{{ name|replace(".", "-") }}
{% endfor %}
{% for name in quadlet_units %}
      - file: telecrypt-quadlet-{{ name|replace(".", "-") }}
{% endfor %}
    - require:
      - file: telecrypt-user-unit-directory
      - file: telecrypt-quadlet-directory
{% for name in service_units %}
      - file: telecrypt-unit-{{ name|replace(".", "-") }}
{% endfor %}
{% for name in quadlet_units %}
      - file: telecrypt-quadlet-{{ name|replace(".", "-") }}
{% endfor %}
