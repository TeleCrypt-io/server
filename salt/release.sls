{#
  The master exposes one selected immutable server release as the Salt file root.
  The release manifest is placed beside the extracted release as
  server-state-images.json before this state is applied. It is the sole image
  selection input; no image tag is resolved on the VM.
#}
{% set release = pillar["telecrypt"]["release"] %}
{% set tag = release["tag"] %}
{% set data_dir = "/home/ubuntu/salt_config" %}
{% set release_dir = data_dir ~ "/releases/" ~ tag %}

telecrypt-release-directory:
  file.directory:
    - name: {{ release_dir }}
    - user: ubuntu
    - group: ubuntu
    - mode: '0755'
    - makedirs: true

telecrypt-release-caddyfile:
  file.managed:
    - name: {{ release_dir }}/Caddyfile
    - source: salt://Caddyfile
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - require:
      - file: telecrypt-release-directory

telecrypt-release-matrix:
  file.recurse:
    - name: {{ release_dir }}/matrix
    - source: salt://matrix
    - user: ubuntu
    - group: ubuntu
    - dir_mode: '0755'
    - file_mode: '0644'
    - clean: true
    - require:
      - file: telecrypt-release-directory

telecrypt-release-salt:
  file.recurse:
    - name: {{ release_dir }}/salt
    - source: salt://salt
    - user: ubuntu
    - group: ubuntu
    - dir_mode: '0755'
    - file_mode: '0644'
    - clean: true
    - require:
      - file: telecrypt-release-directory

telecrypt-release-systemd:
  file.recurse:
    - name: {{ release_dir }}/systemd
    - source: salt://systemd
    - user: ubuntu
    - group: ubuntu
    - dir_mode: '0755'
    - file_mode: '0644'
    - clean: true
    - require:
      - file: telecrypt-release-directory

telecrypt-release-manifest:
  file.managed:
    - name: {{ release_dir }}/server-state-images.json
    - source: salt://server-state-images.json
    - user: ubuntu
    - group: ubuntu
    - mode: '0644'
    - require:
      - file: telecrypt-release-directory

telecrypt-current-release:
  file.symlink:
    - name: {{ data_dir }}/current
    - target: {{ release_dir }}
    - user: ubuntu
    - group: ubuntu
    - force: true
    - atomic: true
    - require:
      - file: telecrypt-release-caddyfile
      - file: telecrypt-release-matrix
      - file: telecrypt-release-salt
      - file: telecrypt-release-systemd
      - file: telecrypt-release-manifest
