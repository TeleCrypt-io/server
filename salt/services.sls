{% set uid = salt["user.info"]("ubuntu").get("uid", 1000)|int %}
{% set unit_dir = "/home/ubuntu/.config/systemd/user" %}
{% set env = {
  "HOME": "/home/ubuntu",
  "XDG_RUNTIME_DIR": "/run/user/" ~ uid|string,
  "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/" ~ uid|string ~ "/bus"
} %}

include:
  - salt.units

telecrypt-target-enabled:
  cmd.run:
    - name: systemctl --user enable --force telecrypt.target
    - runas: ubuntu
    - env: {{ env }}
    - unless: >-
        test "$(readlink -f {{ unit_dir }}/default.target.wants/telecrypt.target)" =
        "$(readlink -f {{ unit_dir }}/telecrypt.target)" &&
        systemctl --user is-enabled telecrypt.target >/dev/null 2>&1
    - require:
      - cmd: telecrypt-user-daemon-reload

telecrypt-janitor-timer-enabled:
  cmd.run:
    - name: systemctl --user enable --force telecrypt-janitor.timer
    - runas: ubuntu
    - env: {{ env }}
    - unless: >-
        test "$(readlink -f {{ unit_dir }}/timers.target.wants/telecrypt-janitor.timer)" =
        "$(readlink -f {{ unit_dir }}/telecrypt-janitor.timer)" &&
        systemctl --user is-enabled telecrypt-janitor.timer >/dev/null 2>&1
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
      - file: telecrypt-unit-telecrypt-janitor-timer
    - require:
      - cmd: telecrypt-janitor-timer-started
