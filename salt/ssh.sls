telecrypt-sshd-drop-in:
  file.managed:
    - name: /etc/ssh/sshd_config.d/90-telecrypt-hardening.conf
    - source: salt://salt/templates/sshd.conf.j2
    - template: jinja
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
