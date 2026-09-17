include:
  - salt.runtime
  - salt.units

{% set operator = pillar["telecrypt"]["operator"] %}
{% set salt_config = pillar["telecrypt"].get("salt", {}) %}

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
      - salt-minion
      - uidmap

telecrypt-cloud-init-hostname:
  file.managed:
    - name: /etc/cloud/cloud.cfg.d/99-telecrypt-hostname.cfg
    - contents: |
        preserve_hostname: true
    - user: root
    - group: root
    - mode: '0644'

telecrypt-container-network-module:
  file.managed:
    - name: /etc/modules-load.d/telecrypt-container-network.conf
    - contents: |
        br_netfilter
    - user: root
    - group: root
    - mode: '0644'

telecrypt-user-manager-delegation:
  file.managed:
    - name: /etc/systemd/system/user@.service.d/delegate.conf
    - contents: |
        [Service]
        Delegate=cpu cpuset io memory pids
    - user: root
    - group: root
    - mode: '0644'
    - makedirs: true

telecrypt-system-daemon-reload:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: telecrypt-user-manager-delegation

telecrypt-subuid:
  file.replace:
    - name: /etc/subuid
    - pattern: '^ubuntu:[0-9]+:[0-9]+$'
    - repl: 'ubuntu:{{ operator["subuid_start"] }}:{{ operator["subordinate_count"] }}'
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
    - repl: 'ubuntu:{{ operator["subgid_start"] }}:{{ operator["subordinate_count"] }}'
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

telecrypt-salt-minion-config:
  file.managed:
    - name: /etc/salt/minion.d/telecrypt.conf
    - contents: |
        master: {{ salt_config.get("master", "192.0.2.20") }}
        id: {{ salt_config.get("minion_id", pillar["telecrypt"]["server"]["name"]) }}
        master_finger: {{ salt_config.get("master_finger", "REPLACE_WITH_SALT_MASTER_FINGERPRINT") }}
        file_client: remote
        pillarenv: base
        saltenv: base
    - user: root
    - group: root
    - mode: '0644'
    - show_changes: false
    - require:
      - pkg: telecrypt-runtime-packages

telecrypt-salt-minion:
  service.running:
    - name: salt-minion
    - enable: true
    - watch:
      - file: telecrypt-salt-minion-config
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
