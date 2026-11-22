"""Strict controller-side planning for PHP-FPM exporter installation and argv."""
import ipaddress
import re
from ansible.errors import AnsibleFilterError


def _fail(message):
    raise AnsibleFilterError('phpfpm_exporter: ' + message)


def _text(value, pattern, field):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        _fail(field + ' has an invalid value')
    return value


def _path(value, field):
    _text(value, r'/[A-Za-z0-9_./-]+', field)
    if any(part in ('', '.', '..') for part in value.split('/')[1:]):
        _fail(field + ' must be a normalized absolute path without whitespace')
    return value


def _list(value, field):
    if not isinstance(value, list):
        _fail(field + ' must be a list')
    return value


def phpfpm_exporter_plan(settings, pools):
    if not isinstance(settings, dict):
        _fail('settings must be a mapping')
    version = _text(settings['version'], r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?', 'version')
    arch = _text(settings['arch'], r'[A-Za-z0-9_]+', 'architecture (set phpfpm_exporter_arch or go_arch)')
    checksum = _text(settings['checksum'], r'[a-fA-F0-9]{64}', 'checksum (set a SHA256 for this release/architecture)')
    for field in ('user', 'group'):
        _text(settings[field], r'[a-z_][a-z0-9_-]*', field)
    if settings['user'] == 'root' or settings['group'] == 'root':
        _fail('root is not an exporter service identity')
    groups = _list(settings['socket_groups'], 'socket_groups')
    if not groups:
        _fail('socket_groups must name the existing PHP socket group')
    for group in groups:
        _text(group, r'[a-z_][a-z0-9_-]*', 'socket group')
    for field in ('binary_path', 'cache_dir', 'systemd_dir', 'socket_dir', 'metrics_path', 'status_path'):
        _path(settings[field], field)
    for field in ('manage_service', 'service_enabled'):
        if not isinstance(settings[field], bool):
            _fail(field + ' must be boolean')
    if settings['manage_service'] and settings['systemd_dir'] not in ('/etc/systemd/system', '/run/systemd/system', '/usr/lib/systemd/system', '/lib/systemd/system'):
        _fail('managed service units must use a standard systemd unit directory')
    listen = settings['listen_address']
    _text(listen, r'(?:[0-9.]*|\[[0-9a-fA-F:]+\]|localhost):[0-9]+', 'listen_address')
    host, port = listen.rsplit(':', 1)
    if not 1 <= int(port) <= 65535:
        _fail('listen port must be between 1 and 65535')
    if host not in ('', 'localhost'):
        try:
            ipaddress.ip_address(host.strip('[]'))
        except ValueError:
            _fail('listen_address must contain a valid IP address')
    sockets = _list(settings['socket_paths'], 'socket_paths')
    if not sockets:
        sockets = []
        for pool in _list(pools, 'php_fpm_conf'):
            if not isinstance(pool, dict):
                _fail('each php_fpm_conf entry must be a mapping')
            name = _text(pool.get('fpm_socket_name'), r'[A-Za-z0-9][A-Za-z0-9_.-]*', 'pool fpm_socket_name')
            php = _text(pool.get('php_version'), r'[0-9]+\.[0-9]+', 'pool php_version (quoted string)')
            sockets.append(settings['socket_dir'] + '/' + name + '-' + php + '.sock')
    if not sockets:
        _fail('set php_fpm_conf with pool/version entries or a nonempty phpfpm_exporter_socket_paths list')
    for socket in sockets:
        _path(socket, 'socket path')
        if len(socket.encode('utf-8')) >= 108:
            _fail('socket path is too long for a Linux Unix-domain socket')
    for runtime_path in sockets + [settings['binary_path']]:
        # Debian's /var/run is an alias of /run, including protected user homes.
        if runtime_path.startswith('/var/run/'):
            runtime_path = '/run/' + runtime_path[len('/var/run/'):]
        if any(runtime_path == prefix or runtime_path.startswith(prefix + '/') for prefix in ('/tmp', '/var/tmp', '/home', '/root', '/run/user')):
            _fail('binary/socket paths under /tmp, /var/tmp, /home, /root or /run/user are hidden by the service sandbox')
    if settings['binary_path'] == settings['systemd_dir'] + '/php_fpm_exporter.service':
        _fail('binary_path and unit path must differ')
    if len(sockets) != len(set(sockets)):
        _fail('socket paths must be unique')
    legacy = _list(settings['legacy_services'], 'legacy_services')
    for unit in legacy:
        _text(unit, r'php_fpm_exporter-[A-Za-z0-9][A-Za-z0-9_.-]*\.service', 'legacy service')
    if legacy and not settings['manage_service']:
        _fail('legacy cleanup requires manage_service=true so old services can be stopped safely')
    archive = 'phpfpm_exporter-' + version + '.linux-' + arch
    return {**settings, 'socket_paths': sorted(sockets), 'socket_groups': sorted(set(groups)),
            'legacy_services': sorted(set(legacy)), 'checksum': checksum.lower(),
            'archive_name': archive,
            'archive_path': settings['cache_dir'] + '/' + archive + '.tar.gz',
            'source_binary': settings['cache_dir'] + '/' + archive + '/phpfpm_exporter',
            'url': 'https://github.com/Lusitaniae/phpfpm_exporter/releases/download/v' + version + '/' + archive + '.tar.gz',
            'unit_path': settings['systemd_dir'] + '/php_fpm_exporter.service'}


class FilterModule:
    def filters(self):
        return {'phpfpm_exporter_plan': phpfpm_exporter_plan}
