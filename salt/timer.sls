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
