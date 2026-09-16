include:
  - salt.runtime
  - salt.units

telecrypt-operator:
  user.present:
    - name: ubuntu
    - remove_groups: false

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

telecrypt-sshd-drop-in:
  file.managed:
    - name: /etc/ssh/sshd_config.d/90-telecrypt-hardening.conf
    - contents: |
        PermitRootLogin no
        PubkeyAuthentication yes
        PasswordAuthentication no
        KbdInteractiveAuthentication no
        X11Forwarding no
        AllowUsers ubuntu
        AllowAgentForwarding no
        AllowTcpForwarding no
    - user: root
    - group: root
    - mode: '0644'
    - check_cmd: /usr/sbin/sshd -t -f
    - show_changes: false
    - require:
      - pkg: telecrypt-runtime-packages

telecrypt-sshd-effective-validation:
  cmd.run:
    - name: /usr/sbin/sshd -t
    - onchanges:
      - file: telecrypt-sshd-drop-in

telecrypt-sshd-reload:
  cmd.run:
    - name: systemctl reload ssh.service
    - onchanges:
      - cmd: telecrypt-sshd-effective-validation
