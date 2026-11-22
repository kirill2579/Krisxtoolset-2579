"""Controller-only PHP input and pathname validation."""
import posixpath
import re
from ansible.errors import AnsibleFilterError


def _fail(message):
    raise AnsibleFilterError(message)


def _sequence(value):
    return isinstance(value, (list, tuple))


def php_pool_plan(versions, pools):
    if not _sequence(versions) or not versions:
        _fail('php_versions must be a nonempty list of quoted major.minor strings.')
    if any(not isinstance(v, str) or not re.fullmatch(r'[0-9]+\.[0-9]+', v) for v in versions):
        _fail('Every php_versions entry must be a quoted major.minor string.')
    if len(set(versions)) != len(versions):
        _fail('php_versions entries must be unique.')
    if not _sequence(pools):
        _fail('php_fpm_conf must be a list of pool mappings.')
    seen, modules, result = set(), {}, []
    for pool in pools:
        if not isinstance(pool, dict):
            _fail('Each php_fpm_conf entry must be a mapping.')
        name, version = pool.get('fpm_socket_name'), pool.get('php_version')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            _fail('Each pool requires a safe fpm_socket_name without directories.')
        if not isinstance(version, str) or version not in versions:
            _fail('Every pool php_version must be a quoted string in php_versions.')
        if (version, name) in seen:
            _fail('Pool names must be unique within each PHP version.')
        seen.add((version, name))
        for key in ('enmodes', 'dismodes'):
            values = pool.get(key, [])
            if not _sequence(values) or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_+-]+', v) for v in values):
                _fail(key + ' must be a list of module names.')
            if values:
                _fail('Pool enmodes/dismodes are obsolete; use global php_enmodes/php_dismodes keyed by cli or fpm.')
            modules.setdefault(version, {'enable': set(), 'disable': set()})['enable' if key == 'enmodes' else 'disable'].update(values)
        for key in ('pm_content', 'memory_limit', 'post_max_size', 'upload_max_filesize'):
            if key in pool and not isinstance(pool[key], str):
                _fail(key + ' must be a string.')
        for key in ('memory_limit', 'post_max_size', 'upload_max_filesize'):
            if key in pool and not re.fullmatch(r'(?:-1|[0-9]+[KMGkmg]?)', pool[key]):
                _fail(key + ' must be an INI size such as 128M, 0, or -1.')
        result.append(pool)
    for version, value in modules.items():
        if value['enable'] & value['disable']:
            _fail('Conflicting enmodes/dismodes for PHP ' + version + '.')
    return {'pools': result, 'versions': [v for v in versions if v in modules],
            'modules': {v: {k: sorted(s) for k, s in values.items()} for v, values in modules.items()}}


def php_safe_path(value):
    if not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value) or value == '/' or posixpath.normpath(value) != value or '//' in value:
        _fail('PHP paths must be absolute normalized paths without whitespace or metacharacters: ' + str(value))
    return value


def php_path_ancestors(paths):
    result = set()
    for path in paths:
        path = php_safe_path(path)
        while path != '/':
            result.add(path)
            path = posixpath.dirname(path)
    if '/var/run' in result:
        result.add('/run')
    return sorted(result, key=lambda p: (p.count('/'), p))


def php_path_identity(value):
    value = php_safe_path(value)
    return '/run' + value[len('/var/run'):] if value == '/var/run' or value.startswith('/var/run/') else value


def php_assert_destinations(files, directories):
    paths = [php_path_identity(f['dest']) for f in files]
    dirs = [php_path_identity(d) for d in directories]
    if len(paths) != len(set(paths)):
        _fail('Managed PHP filenames must be distinct across versions and templates.')
    for path in paths:
        if any(d == path or d.startswith(path + '/') for d in dirs):
            _fail('A managed PHP file cannot also be a parent directory: ' + path)
    return True


def php_validate_pool_render(content, pool, socket_dir):
    expected = php_safe_path(socket_dir) + '/' + pool['fpm_socket_name'] + '-' + pool['php_version'] + '.sock'
    if len(expected.encode('utf-8')) >= 108:
        _fail('The PHP pool socket pathname is too long for a Linux Unix-domain socket.')
    listeners = re.findall(r'^\s*listen\s*=\s*([^;\r\n]+?)\s*(?:;.*)?$', content, re.MULTILINE)
    if listeners != [expected]:
        _fail('Each PHP pool template must emit exactly listen = ' + expected)
    sections = re.findall(r'^\s*\[([^]\r\n]+)\]\s*$', content, re.MULTILINE)
    if sections != [pool['fpm_socket_name']]:
        _fail('Each PHP pool template must emit exactly its own named pool section.')
    return content


def php_clean_diagnostics(result):
    # PHP can report a startup or INI parse error and still return exit status 0.
    # FPM's normal successful -t NOTICE on stderr is not an error.
    output = result.get('stdout', '') + '\n' + result.get('stderr', '')
    return not result.get('failed', False) and result.get('rc', 0) == 0 and not re.search(
        r'(?i)(?:PHP\s+(?:Warning|Fatal|Parse|Startup|Deprecated|Notice|Recoverable)|PHP:|syntax\s+error|'
        r'\b(?:WARNING|ERROR|FATAL):|Unable to load|failed to (?:open|load))', output)


class FilterModule:
    def filters(self):
        return {'php_pool_plan': php_pool_plan, 'php_safe_path': php_safe_path,
                'php_path_ancestors': php_path_ancestors, 'php_assert_destinations': php_assert_destinations,
                'php_path_identity': php_path_identity, 'php_validate_pool_render': php_validate_pool_render, 'php_clean_diagnostics': php_clean_diagnostics}
