"""Read-only TLS checks; never print private key material."""
import os
import stat
import subprocess
import sys


def run(*args):
    result = subprocess.run(['openssl', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise ValueError('TLS validation failed')
    return result.stdout


def validate(bundle, ca, hostname):
    info = os.lstat(bundle)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ValueError('Service PEM must be a regular, service-owned private file')
    run('x509', '-in', bundle, '-noout', '-checkend', '86400')
    for purpose in ('sslserver', 'sslclient'):
        for name in (hostname, 'localhost'):
            run('verify', '-CAfile', ca, '-purpose', purpose, '-verify_hostname', name, bundle)
    eku = run('x509', '-in', bundle, '-noout', '-ext', 'extendedKeyUsage').decode()
    if 'TLS Web Server Authentication' not in eku or 'TLS Web Client Authentication' not in eku:
        raise ValueError('Explicit serverAuth and clientAuth EKUs are required')
    san = run('x509', '-in', bundle, '-noout', '-ext', 'subjectAltName').decode()
    names = {part.strip() for part in san.split('\n', 1)[-1].split(',')}
    if not {'DNS:' + hostname, 'DNS:localhost'}.issubset(names):
        raise ValueError('Explicit member and localhost DNS SANs are required')
    cert_public = run('x509', '-in', bundle, '-pubkey', '-noout')
    key_public = run('pkey', '-in', bundle, '-pubout')
    if cert_public != key_public:
        raise ValueError('Service certificate and private key do not match')


if __name__ == '__main__':
    try:
        validate(*sys.argv[1:])
    except Exception:
        sys.exit('TLS validation failed; check ownership, permissions, CA, key, SANs, EKUs and expiry')
