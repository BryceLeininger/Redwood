@echo off
set CERT_PATH=outlook_addin\certs\localhost.crt
set KEY_PATH=outlook_addin\certs\localhost.key

if not exist "%CERT_PATH%" (
  echo Localhost certificate not found. Generating and trusting certificate...
  python -m agent_factory.create_localhost_cert --trust
)

python -m agent_factory.outlook_panel_server --host 127.0.0.1 --port 8765 --ssl-certfile "%CERT_PATH%" --ssl-keyfile "%KEY_PATH%"
