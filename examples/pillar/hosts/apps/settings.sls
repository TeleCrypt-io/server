network:
  private_address: 192.0.2.20
  matrix_address: 192.0.2.10
  ssh_port: 22

deployment:
  environment: stage
  role: apps

endpoints:
  mas_admin_url: http://192.0.2.10:8080
  mas_internal_url: http://192.0.2.10:8080
  synapse_admin_url: http://192.0.2.10:8080
