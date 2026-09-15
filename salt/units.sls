{% set unit_dir = "/home/ubuntu/.config/systemd/user" %}
{% set quadlet_dir = "/home/ubuntu/.config/containers/systemd" %}

include:
  - salt.account

telecrypt-user-unit-directory:
  file.directory:
    - name: {{ unit_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0700'
    - makedirs: true
    - require:
      - user: telecrypt-operator

telecrypt-quadlet-directory:
  file.directory:
    - name: {{ quadlet_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0775'
    - makedirs: true
    - require:
      - user: telecrypt-operator

{% for name in ("telecrypt-pod.service", "telecrypt.target", "telecrypt-janitor.service") %}
telecrypt-unit-link-{{ name|replace(".", "-") }}:
  file.symlink:
    - name: {{ unit_dir }}/{{ name }}
    - target: /home/ubuntu/telecrypt-current/systemd/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - force: true
    - atomic: true
    - require:
      - file: telecrypt-user-unit-directory
{% endfor %}

{% for name in ("telecrypt-caddy.container", "telecrypt-cashier.container", "telecrypt-mas.container", "telecrypt-plan.container", "telecrypt-registration.container", "telecrypt-synapse.container") %}
telecrypt-quadlet-link-{{ name|replace(".", "-") }}:
  file.symlink:
    - name: {{ quadlet_dir }}/{{ name }}
    - target: /home/ubuntu/telecrypt-current/systemd/quadlet/{{ name }}
    - user: ubuntu
    - group: ubuntu
    - force: true
    - atomic: true
    - require:
      - file: telecrypt-quadlet-directory
{% endfor %}

telecrypt-old-janitor-timer-link:
  cmd.run:
    - name: /usr/bin/unlink /home/ubuntu/.config/systemd/user/telecrypt-janitor.timer
    - onlyif: /usr/bin/test -L /home/ubuntu/.config/systemd/user/telecrypt-janitor.timer

telecrypt-janitor-timer-file:
  file.managed:
    - name: {{ unit_dir }}/telecrypt-janitor.timer
    - source: salt://systemd/telecrypt-janitor.timer
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - require:
      - file: telecrypt-user-unit-directory
      - cmd: telecrypt-old-janitor-timer-link
