include:
  - salt.account
  - salt.runtime
  - salt.ssh
  - salt.units

telecrypt-runtime-packages:
  pkg.installed:
    - pkgs:
      - ca-certificates
      - curl
      - dbus-user-session
      - gnupg
      - openssh-server
      - passt
      - podman
      - uidmap

telecrypt-subuid:
  file.replace:
    - name: /etc/subuid
    - pattern: '^ubuntu:[0-9]+:[0-9]+$'
    - repl: 'ubuntu:{{ pillar["telecrypt"]["subuid_start"] }}:{{ pillar["telecrypt"]["subordinate_count"] }}'
    - count: 1
    - append_if_not_found: true
    - backup: false
    - flags:
      - MULTILINE
    - require:
      - user: telecrypt-operator

telecrypt-subgid:
  file.replace:
    - name: /etc/subgid
    - pattern: '^ubuntu:[0-9]+:[0-9]+$'
    - repl: 'ubuntu:{{ pillar["telecrypt"]["subgid_start"] }}:{{ pillar["telecrypt"]["subordinate_count"] }}'
    - count: 1
    - append_if_not_found: true
    - backup: false
    - flags:
      - MULTILINE
    - require:
      - user: telecrypt-operator

telecrypt-linger:
  cmd.run:
    - name: loginctl enable-linger ubuntu
    - unless: loginctl show-user ubuntu -p Linger --value | grep -qx yes
    - shell: /bin/bash
    - require:
      - user: telecrypt-operator

salt-minion-stopped:
  service.dead:
    - name: salt-minion
    - enable: false
    - require:
      - pkg: telecrypt-runtime-packages
