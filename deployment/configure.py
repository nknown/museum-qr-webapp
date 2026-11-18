#!/usr/bin/env python3
"""Create private university deployment configuration without editing source."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--origin',
        required=True,
        help='Public HTTPS origin, e.g. https://museum.example.edu',
    )
    parser.add_argument('--http-port', type=int, default=80)
    parser.add_argument(
        '--self-signed',
        action='store_true',
        help='Generate a lab-only certificate; otherwise supply university certificates.',
    )
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    try:
        port = origin.port if origin.port is not None else 443
    except ValueError:
        parser.error('invalid HTTPS port')
    host = origin.hostname or ''
    try:
        ipaddress.ip_address(host)
    except ValueError:
        host_is_ip = False
    else:
        host_is_ip = True
    if (origin.scheme != 'https' or not host or host_is_ip or '.' not in host
            or origin.username or origin.password
            or origin.path not in ('', '/') or origin.query or origin.fragment
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', host)
            or not 1 <= port <= 65535
            or not 1 <= args.http_port <= 65535 or port == args.http_port):
        parser.error(
            'use an HTTPS DNS hostname with a domain suffix, optional port, '
            'and no path; HTTP and HTTPS ports must differ'
        )
    origin_text = f'https://{host}' + (f':{port}' if port != 443 else '')
    accepted_hosts = [host]
    trusted_origins = [
        f'https://{accepted_host}' + (f':{port}' if port != 443 else '')
        for accepted_host in accepted_hosts
    ]
    directory = Path(__file__).resolve().parent
    env_path = directory / 'deployment.env'
    if env_path.exists():
        parser.error(
            'deployment.env already exists; keep its secrets when changing configuration'
        )
    tls = directory / 'tls'
    tls.mkdir(mode=0o700, exist_ok=True)
    if args.self_signed:
        cert, key = tls / 'fullchain.pem', tls / 'privkey.pem'
        if cert.exists() or key.exists():
            parser.error('refusing to replace existing TLS material')
        subprocess.run([
            'openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048',
            '-sha256', '-days', '90', '-keyout', str(key), '-out', str(cert),
            '-subj', f'/CN={host}', '-addext', f'subjectAltName=DNS:{host}',
            '-addext', 'extendedKeyUsage=serverAuth',
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        key.chmod(0o600)
    values = {
        'PUBLIC_HOSTNAME': host,
        'PUBLIC_ORIGIN': origin_text,
        'HTTPS_PORT': str(port),
        'HTTP_PORT': str(args.http_port),
        'MAIN_APP_ALLOWED_HOSTS': ','.join(accepted_hosts),
        'MAIN_APP_CSRF_TRUSTED_ORIGINS': ','.join(trusted_origins),
        'MAIN_APP_PRODUCTION': 'on',
        'MAIN_APP_REVERSE_PROXY': 'on',
        'MAIN_APP_SECRET': secrets.token_urlsafe(64),
        'POSTGRES_DB_PASSWORD': secrets.token_urlsafe(36),
        'POSTGRES_MAX_CONNECTIONS': '100',
        'MIYP_HTTP_CONCURRENCY_LIMIT': '75',
        'SERVER_NAME': origin_text + '/',
        'WAGTAILADMIN_BASE_URL': origin_text + '/cms',
        'MAIN_APP_GOOGLE_OAUTH': 'off',
        'MAIN_APP_MS_OAUTH': 'off',
        'GOOGLE_OAUTH_USE_LOOPBACK_REDIRECT': 'off',
        'SECURE_HSTS_SECONDS': '3600',
        'TELEMETRY_LIMIT_DRY_RUN': 'on',
    }
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('# Private configuration. Do not commit or include in thesis evidence.\n')
        stream.writelines(f'{key}={value}\n' for key, value in values.items())
    print(f'Created {env_path}; secrets are not printed.')
    if not args.self_signed:
        print(f'Install the certificate chain and private key in {tls}/fullchain.pem and privkey.pem before starting Nginx.')


if __name__ == '__main__':
    main()
