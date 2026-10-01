include:
  - apps.runtime
  - apps.units

apps-pod-running:
  user_service.running:
    - name: apps-pod.service
    - user: ubuntu
    - timeout: 900
    - require:
      - service: salt-user-manager
      - user_service: apps-pod-quiescent
      - file: apps-pod-quadlet
      - file: apps-cashier-quadlet
      - file: apps-plan-quadlet
      - file: apps-registration-quadlet
      - file: apps-janitor-quadlet

apps-cashier-running:
  user_service.running:
    - name: cashier.service
    - user: ubuntu
    - timeout: 900
    - require:
      - user_service: apps-pod-running
      - user_service: apps-cashier-quiescent
      - file: apps-cashier-quadlet
      - file: apps-secret-cashier-secrets-env
      - file: apps-secret-cashier-plan-token-env
      - file: apps-secret-cashier-synapse-token-env
      - file: apps-secret-cashier-janitor-token-env
      - file: apps-secret-cashier-dodo-webhook-secret-env

apps-registration-running:
  user_service.running:
    - name: registration.service
    - user: ubuntu
    - timeout: 900
    - require:
      - user_service: apps-pod-running
      - user_service: apps-registration-quiescent
      - file: apps-registration-quadlet

apps-plan-running:
  user_service.running:
    - name: plan.service
    - user: ubuntu
    - timeout: 900
    - require:
      - user_service: apps-cashier-running
      - user_service: apps-plan-quiescent
      - file: apps-plan-quadlet
      - file: apps-secret-plan-secrets-env
      - file: apps-secret-cashier-plan-token-env

# Enabling and starting the timer schedules the one-shot; Salt never starts Janitor itself.
apps-janitor-timer-running:
  user_service.running:
    - name: janitor.timer
    - user: ubuntu
    - require:
      - user_service: apps-plan-running
      - user_service: apps-janitor-timer-quiescent
      - file: apps-janitor-quadlet
      - file: apps-janitor-timer
      - file: apps-janitor-timer-enabled
      - file: apps-secret-janitor-secrets-env
      - file: apps-secret-cashier-janitor-token-env
