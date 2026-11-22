"""Controller-only planning and verification for Debian's PHP module helpers.

phpenmod/phpdismod may return zero after refusing a module. Never infer success
from their return code: verify both the live link and the administrative state.
The helpers' absolute paths and marker semantics are documented in php-defaults:
https://sources.debian.org/src/php-defaults/102~/phpenmod
https://sources.debian.org/src/php-defaults/93/php-helper
"""
import base64
import re
from ansible.errors import AnsibleFilterError


MARKERS = ('enabled_by_admin', 'enabled_by_maint',
           'disabled_by_admin', 'disabled_by_maint')


def _fail(message):
    raise AnsibleFilterError(message)


def php_module_plan(versions, enmodes, dismodes):
    if not isinstance(versions, list) or not versions or any(
            not isinstance(v, str) or not re.fullmatch(r'[0-9]+\.[0-9]+', v)
            for v in versions) or len(set(versions)) != len(versions):
        _fail('php_versions must be a nonempty list of unique quoted major.minor strings.')
    settings = []
    for name, value in (('php_enmodes', enmodes), ('php_dismodes', dismodes)):
        if not isinstance(value, dict) or set(value) - {'cli', 'fpm'}:
            _fail(name + ' must be a mapping keyed only by cli and/or fpm.')
        for modules in value.values():
            if not isinstance(modules, list) or any(
                    not isinstance(m, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_+-]*', m)
                    for m in modules):
                _fail(name + ' values must be lists of module names without paths, options, or .ini suffixes.')
            if len(set(modules)) != len(modules):
                _fail(name + ' module lists must not contain duplicates.')
        settings.append(value)
    for sapi in ('cli', 'fpm'):
        if set(enmodes.get(sapi, [])) & set(dismodes.get(sapi, [])):
            _fail('A module cannot appear in both php_enmodes and php_dismodes for the same SAPI.')
    return [{'version': version, 'sapi': sapi, 'module': module, 'state': state}
            for version in versions for sapi in ('cli', 'fpm')
            for value, state in zip(settings, ('enabled', 'disabled'))
            for module in value.get(sapi, [])]


def php_module_paths(plan):
    """The distribution helpers deliberately have no configurable root option."""
    return [dict(item, source='/etc/php/{version}/mods-available/{module}.ini'.format(**item),
                 conf_dir='/etc/php/{version}/{sapi}/conf.d'.format(**item),
                 markers=[dict(path='/var/lib/php/modules/{version}/{sapi}/'.format(**item)
                               + state + '/' + item['module'], state=state)
                          for state in MARKERS]) for item in plan]


def php_module_targets(paths, reads):
    if len(paths) != len(reads):
        _fail('Incomplete PHP module source snapshot.')
    result = []
    for item, read in zip(paths, reads):
        priorities = []
        for line in base64.b64decode(read['content']).decode('latin1').splitlines():
            match = re.fullmatch(r';[^\S\r\n]*priority[^\S\r\n]*=[^\S\r\n]*([0-9]+)[^\S\r\n]*', line)
            if match:
                priorities.append(match.group(1))
            # This also matches the distribution helper's sed early-stop rule.
            if re.fullmatch(r'[0-9]+', line):
                break
        if len(priorities) > 1:
            _fail('A requested PHP module has multiple priority declarations; fix its mods-available INI first.')
        priority = priorities[0] if priorities else '20'
        result.append(dict(item, link=item['conf_dir'] + '/' + priority + '-' + item['module'] + '.ini'))
    return result


def php_module_snapshot(targets, link_stats, marker_stats, found, backup_root=''):
    """Validate the entire set before helpers mutate any target; capture recovery."""
    if len(targets) != len(link_stats) or len(targets) != len(found) or len(marker_stats) != 4 * len(targets):
        _fail('Incomplete PHP module state inspection.')
    links, markers, changes, changed_versions = [], [], [], []
    for index, item in enumerate(targets):
        link = link_stats[index]['stat']
        # Alternate priority links would remain loaded after a successful dismod.
        if found[index].get('skipped_paths') or found[index].get('failed'):
            _fail('A PHP module conf.d directory could not be inspected completely.')
        if any(f['path'] != item['link'] for f in found[index].get('files', [])):
            _fail('A requested PHP module has an unexpected conf.d filename or duplicate priority; reconcile it first.')
        exists = bool(link.get('exists', False) or link.get('islnk', False))
        if exists and (not link.get('islnk', False) or link.get('lnk_target') != item['source']):
            _fail('A requested PHP module conf.d entry is broken, nonstandard, or not a distribution-managed symlink.')
        links.append(dict(path=item['link'], exists=exists,
                          target=link.get('lnk_target', ''), uid=link.get('uid', 0), gid=link.get('gid', 0)))
        existing_markers = []
        for offset, spec in enumerate(item['markers']):
            marker = marker_stats[index * 4 + offset]['stat']
            present = marker.get('exists', False)
            if present and (not marker.get('isreg', False) or marker.get('islnk', False)):
                _fail('PHP module administrative markers must be regular files or absent.')
            if present:
                existing_markers.append(spec['state'])
            markers.append(dict(path=spec['path'], exists=present,
                                backup=backup_root + '/module-marker-' + str(index * 4 + offset) if backup_root else '',
                                mode=marker.get('mode', '0644'),
                                uid=marker.get('uid', 0), gid=marker.get('gid', 0)))
        if len(existing_markers) > 1:
            _fail('A requested PHP module has conflicting administrative markers; reconcile them first.')
        desired_exists = item['state'] == 'enabled'
        if exists != desired_exists or existing_markers != [item['state'] + '_by_admin']:
            changes.append(item)
        if exists != desired_exists and item['sapi'] == 'fpm' and item['version'] not in changed_versions:
            changed_versions.append(item['version'])
    return dict(links=links, markers=markers, targets=targets, changes=changes,
                changed_versions=changed_versions)


def php_module_verify(targets, link_stats, marker_stats, found):
    if len(targets) != len(link_stats) or len(targets) != len(found) or len(marker_stats) != 4 * len(targets):
        return False
    for index, item in enumerate(targets):
        link = link_stats[index]['stat']
        exists = bool(link.get('exists', False) or link.get('islnk', False))
        if item['state'] == 'enabled':
            if not exists or not link.get('islnk', False) or link.get('lnk_target') != item['source']:
                return False
        elif exists:
            return False
        if found[index].get('skipped_paths') or found[index].get('failed'):
            return False
        if any(f['path'] != item['link'] for f in found[index].get('files', [])):
            return False
        for offset, spec in enumerate(item['markers']):
            marker = marker_stats[index * 4 + offset]['stat']
            if bool(marker.get('exists', False)) != (spec['state'] == item['state'] + '_by_admin'):
                return False
            if marker.get('exists', False) and (not marker.get('isreg', False) or marker.get('islnk', False)):
                return False
    return True


def php_module_fingerprint(targets, source_stats, link_stats, marker_stats):
    """Retain exact post-helper state for a later deferred-activation guard."""
    if len(targets) != len(source_stats) or len(targets) != len(link_stats) or len(marker_stats) != 4 * len(targets):
        _fail('Incomplete PHP module activation-state inspection.')
    fields = ('exists', 'isreg', 'islnk', 'checksum', 'mode', 'uid', 'gid', 'lnk_target')
    def state(result):
        if result.get('failed') or 'stat' not in result or 'exists' not in result['stat']:
            _fail('PHP module activation-state inspection failed.')
        return {field: result['stat'][field] for field in fields if field in result['stat']}
    return {'sources': [state(result) for result in source_stats],
            'links': [state(result) for result in link_stats],
            'markers': [state(result) for result in marker_stats]}


def php_module_recovery_safe(path, ancestors, leaves, kind):
    """Do not follow a new symlink or delete an unexpected directory in rescue."""
    for result in ancestors:
        parent = result['item']
        if path.startswith(parent + '/'):
            state = result.get('stat', {})
            if result.get('failed') or 'exists' not in state:
                return False
            if state.get('exists') and (not state.get('isdir') or state.get('islnk')):
                return False
    for result in leaves:
        if result['item']['path'] == path:
            state = result.get('stat', {})
            if result.get('failed') or 'exists' not in state:
                return False
            if not state.get('exists') and not state.get('islnk'):
                return True
            return bool(state.get('islnk')) if kind == 'link' else bool(state.get('isreg') and not state.get('islnk'))
    return False


def php_module_no_pending_overlap(plan, transactions):
    current = {(p['version'], p['sapi'], p['module']) for p in plan}
    for transaction in transactions:
        if current & {(p['version'], p['sapi'], p['module'])
                      for p in transaction.get('module_recovery', {}).get('targets', [])}:
            return False
    return True


class FilterModule:
    def filters(self):
        return {'php_module_plan': php_module_plan, 'php_module_paths': php_module_paths,
                'php_module_targets': php_module_targets, 'php_module_snapshot': php_module_snapshot,
                'php_module_verify': php_module_verify,
                'php_module_fingerprint': php_module_fingerprint,
                'php_module_recovery_safe': php_module_recovery_safe,
                'php_module_no_pending_overlap': php_module_no_pending_overlap}
