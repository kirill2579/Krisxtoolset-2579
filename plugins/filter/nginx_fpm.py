"""Resolve bundled nginx upstreams without guessing a PHP version."""
import re
from collections.abc import Mapping

from ansible.errors import AnsibleFilterError


def _path(value):
    if (not isinstance(value, str)
            or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value)
            or any(part in ('', '.', '..') for part in value.split('/')[1:])):
        raise AnsibleFilterError('FPM socket paths must be normalized absolute paths.')
    return value


def nginx_fpm_socket(server, pools=None, socket_dir='/var/run/fpm'):
    """Explicit path, selected/matched version, otherwise the legacy external pool."""
    if not isinstance(server, Mapping):
        raise AnsibleFilterError('FPM server must be a mapping.')
    if 'fpm_socket_path' in server:
        return _path(server['fpm_socket_path'])
    name = server.get('fpm_socket_name')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
        raise AnsibleFilterError('FPM socket name must start with a letter/digit and contain only letters, digits, _, . or -.')
    if pools is None:
        pools = []
    if not isinstance(pools, list) or any(not isinstance(pool, Mapping) for pool in pools):
        raise AnsibleFilterError('php_fpm_conf must be a list of pool mappings.')
    matches = [pool for pool in pools if pool.get('fpm_socket_name') == name]
    versions = [pool.get('php_version') for pool in matches]
    for version in versions:
        if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+', version):
            raise AnsibleFilterError('Matching FPM pools require quoted PHP major.minor versions.')
    version = server.get('php_version')
    if 'php_version' in server:
        if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+', version):
            raise AnsibleFilterError('server.php_version must be a quoted PHP major.minor version.')
        if matches and version not in versions:
            raise AnsibleFilterError('server.php_version does not match a configured FPM pool.')
    elif len(set(versions)) > 1:
        raise AnsibleFilterError('Multiple PHP versions match the FPM pool; set server.php_version or fpm_socket_path.')
    elif versions:
        version = versions[0]
    if version is not None:
        return _path(socket_dir) + '/' + name + '-' + version + '.sock'
    # An unrelated PHP pool must not rename an externally managed legacy socket.
    return '/var/run/fpm/php-fpm.' + name + '.sock'


class FilterModule:
    def filters(self):
        return {'nginx_fpm_socket': nginx_fpm_socket}
