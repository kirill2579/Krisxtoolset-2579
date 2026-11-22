#!/usr/bin/python
"""Structural native Redis config writer; no candidate processes or service management."""
import grp
import hashlib
import os
from pathlib import Path
import re
import shlex
import stat
import tempfile

DOCUMENTATION = r'''
---
module: redis_config
short_description: Validate and write a standalone Redis configuration
version_added: '0.1.1'
description:
  - Updates the distro Redis configuration atomically and backs up the previous file.
  - Does not start Redis; the calling role handles service activation and recovery.
options:
  settings:
    description: Mapping with loopback bind addresses, port and explicitly selected native directives.
    type: dict
    required: true
  adopt_existing_config:
    description: Allow replacing an existing configuration not owned by the role.
    type: bool
    default: false
author:
  - KrisX
'''

MARKER = '# Managed by Krisxtoolset redis role\n'
CONFIG = '/etc/redis/redis.conf'


OWNED_DIRECTIVES = frozenset("""
bind port daemonize supervised pidfile logfile dir dbfilename appendfilename
appenddirname unixsocket unixsocketperm
""".split())


def quote(value):
    """Encode one Redis argument, never an executable configuration line."""
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def arguments(name, value):
    if name.lower() == 'requirepass' and not isinstance(value, str):
        raise ValueError('redis_config requirepass must be a literal string')
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('redis_config values must be strings or integers (quote yes/no)')
    value = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('redis_config values must not contain control characters or newlines')
    # Passwords are literal strings, not native argument expressions.
    if name.lower() == 'requirepass' or value == '':
        return [value]
    try:
        tokens = shlex.split(value, comments=False, posix=True)
    except ValueError:
        raise ValueError('redis_config contains invalid argument quoting') from None
    if not tokens or any(any(ord(c) < 32 or ord(c) == 127 for c in token) for token in tokens):
        raise ValueError('redis_config contains an empty or invalid argument expression')
    return tokens


def render(settings):
    """Validate the standalone contract before rendering a complete config."""
    if set(settings) - {'bind', 'port', 'config'}:
        raise ValueError('Removed Redis settings: use the native redis_config dictionary')
    binds = settings['bind']
    if (not isinstance(binds, list) or not binds or len(set(map(str, binds))) != len(binds)
            or any(value not in ('127.0.0.1', '::1') for value in binds)):
        raise ValueError('redis_bind must be a nonempty unique list of loopback addresses')
    port = settings['port']
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('redis_port must be an integer from 1 to 65535')
    config = settings['config']
    if not isinstance(config, dict):
        raise ValueError('redis_config must be a dictionary of native directives')
    for name in config:
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', name):
            raise ValueError('redis_config directive names must be single native names (letters, digits, dots, underscores or hyphens)')
        if name.lower() in OWNED_DIRECTIVES:
            raise ValueError('redis_config directive ' + name + ' is role-owned; use redis_bind/redis_port for networking')
        if name.lower() == 'include':
            raise ValueError('redis_config include is unsupported because imported files can override role-owned settings; put directives directly in redis_config')
    lines = [MARKER.rstrip(), 'bind ' + ' '.join(binds), f'port {port}',
             'daemonize no', 'supervised systemd', 'pidfile /run/redis/redis-server.pid',
             'logfile /var/log/redis/redis-server.log', 'dir /var/lib/redis',
             'dbfilename dump.rdb', 'appendfilename "appendonly.aof"',
             'appenddirname "appendonlydir"']
    for name, value in config.items():
        values = value if isinstance(value, list) else [value]
        if not values or (name.lower() == 'requirepass' and isinstance(value, list)):
            raise ValueError('redis_config lists must be nonempty; requirepass must be a scalar')
        for item in values:
            lines.append(name + ' ' + ' '.join(quote(token) for token in arguments(name, item)))
    return '\n'.join(lines) + '\n'


def inspect_existing(path, adopt):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected an existing regular distro redis.conf; install redis-server first')
    content = path.read_text()
    if not content.startswith(MARKER) and not adopt:
        raise ValueError('Unmanaged redis.conf: review/back up configuration and data, then set redis_adopt_existing_config=true')
    return content


def main():
    from ansible.module_utils.basic import AnsibleModule
    module = AnsibleModule(argument_spec={
        'settings': {'type': 'dict', 'required': True, 'no_log': True},
        'adopt_existing_config': {'type': 'bool', 'default': False},
    }, supports_check_mode=True)
    try:
        content = render(module.params['settings'])
        previous = inspect_existing(CONFIG, module.params['adopt_existing_config'])
        group = grp.getgrnam('redis')
        metadata = os.stat(CONFIG)
        changed = (previous != content or metadata.st_uid != 0 or metadata.st_gid != group.gr_gid
                   or stat.S_IMODE(metadata.st_mode) != 0o640)
        result = {'changed': changed, 'checksum': hashlib.sha256(content.encode()).hexdigest()}
        if changed and not module.check_mode:
            result['backup_file'] = module.backup_local(CONFIG)
            os.chmod(result['backup_file'], 0o600)
            fd, candidate = tempfile.mkstemp(dir=module.tmpdir)
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(content)
                os.chown(candidate, 0, group.gr_gid)
                os.chmod(candidate, 0o640)
                module.atomic_move(candidate, CONFIG, keep_dest_attrs=False)
            finally:
                if os.path.exists(candidate):
                    os.unlink(candidate)
        module.exit_json(**result)
    except ValueError as exc:
        # Our validation errors never interpolate directive values or native logs.
        module.fail_json(msg='Redis configuration validation failed', safe_error=str(exc))
    except (KeyError, OSError):
        module.fail_json(msg='Redis configuration failed; inspect package files and permissions')


if __name__ == '__main__':
    main()
