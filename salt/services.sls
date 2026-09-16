{% set uid = pillar["telecrypt"]["operator_uid"]|int %}
{% set env = {
  "HOME": "/home/ubuntu",
  "XDG_RUNTIME_DIR": "/run/user/" ~ uid|string,
  "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/" ~ uid|string ~ "/bus"
} %}

include:
  - salt.units

telecrypt-old-janitor-timer-link:
  cmd.run:
    - name: /usr/bin/unlink /home/ubuntu/.config/systemd/user/telecrypt-janitor.timer
    - onlyif: /usr/bin/test -L /home/ubuntu/.config/systemd/user/telecrypt-janitor.timer

telecrypt-janitor-timer-file:
  file.managed:
    - name: /home/ubuntu/.config/systemd/user/telecrypt-janitor.timer
    - source: salt://systemd/telecrypt-janitor.timer
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - require:
      - file: telecrypt-user-unit-directory
      - cmd: telecrypt-old-janitor-timer-link

telecrypt-user-daemon-reload:
  cmd.run:
    - name: systemctl --user daemon-reload
    - runas: ubuntu
    - env: {{ env }}
    - onchanges:
      - file: telecrypt-janitor-timer-file
{% for name in ("telecrypt-pod.service", "telecrypt.target", "telecrypt-janitor.service") %}
      - file: telecrypt-unit-link-{{ name|replace(".", "-") }}
{% endfor %}
{% for name in ("telecrypt-caddy.container", "telecrypt-cashier.container", "telecrypt-lk-jwt.container", "telecrypt-mas.container", "telecrypt-plan.container", "telecrypt-registration.container", "telecrypt-synapse.container") %}
      - file: telecrypt-quadlet-link-{{ name|replace(".", "-") }}
{% endfor %}
    - require:
      - file: telecrypt-janitor-timer-file
{% for name in ("telecrypt-pod.service", "telecrypt.target", "telecrypt-janitor.service") %}
      - file: telecrypt-unit-link-{{ name|replace(".", "-") }}
{% endfor %}
{% for name in ("telecrypt-caddy.container", "telecrypt-cashier.container", "telecrypt-lk-jwt.container", "telecrypt-mas.container", "telecrypt-plan.container", "telecrypt-registration.container", "telecrypt-synapse.container") %}
      - file: telecrypt-quadlet-link-{{ name|replace(".", "-") }}
{% endfor %}

telecrypt-target-enabled:
  cmd.run:
    - name: systemctl --user enable telecrypt.target
    - runas: ubuntu
    - env: {{ env }}
    - unless: systemctl --user is-enabled telecrypt.target >/dev/null 2>&1
    - require:
      - cmd: telecrypt-user-daemon-reload

telecrypt-janitor-timer-enabled:
  cmd.run:
    - name: systemctl --user enable telecrypt-janitor.timer
    - runas: ubuntu
    - env: {{ env }}
    - unless: systemctl --user is-enabled telecrypt-janitor.timer >/dev/null 2>&1
    - require:
      - cmd: telecrypt-user-daemon-reload

telecrypt-janitor-timer-started:
  cmd.run:
    - name: systemctl --user start telecrypt-janitor.timer
    - runas: ubuntu
    - env: {{ env }}
    - unless: systemctl --user is-active telecrypt-janitor.timer >/dev/null 2>&1
    - require:
      - cmd: telecrypt-janitor-timer-enabled

telecrypt-janitor-timer-restarted-after-change:
  cmd.run:
    - name: systemctl --user restart telecrypt-janitor.timer
    - runas: ubuntu
    - env: {{ env }}
    - onchanges:
      - file: telecrypt-janitor-timer-file
    - require:
      - cmd: telecrypt-janitor-timer-started
