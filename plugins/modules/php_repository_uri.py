#!/usr/bin/python
"""Change only the native ondrej/php role entry after apt_repository bootstraps trust."""

import os
import re
import stat
import tempfile


DOCUMENTATION = r'''
---
module: php_repository_uri
short_description: Inspect or migrate the PHP role's native PPA source URI
description:
  - Does not create repositories, import keys, or edit other source files.
options:
  codename:
    description: Ubuntu suite name to match in the existing source.
    type: str
    required: true
  uri:
    description: Official PHP HTTPS URI or an absolute mirror list URI.
    type: str
    required: true
  state:
    description: Inspect the existing entry or apply the requested URI.
    type: str
    choices: [inspect, present]
    default: present
author:
  - Krisxtoolset
'''

ORIGINAL_URI = 'https://ppa.launchpadcontent.net/ondrej/php/ubuntu'
SOURCE_DIRECTORY = '/etc/apt/sources.list.d'
LEGACY_URIS = {
    scheme + '://' + host + '/ondrej/php/ubuntu'
    for scheme in ('http', 'https')
    for host in ('ppa.launchpad.net', 'ppa.launchpadcontent.net')
}
MARKER = 'krisxtoolset:php-repository'
MIRROR_URI = re.compile(r'mirror\+file:/[A-Za-z0-9_./-]+\.list\Z')
SOURCE = re.compile(
    r'(?P<head>[ \t]*(?P<kind>deb(?:-src)?)[ \t]+'
    r'(?:\[[^\]\r\n]+\][ \t]+)?)'
    r'(?P<uri>[^ \t\r\n]+)'
    r'(?P<tail>[ \t]+(?P<suite>[^ \t\r\n#]+)[ \t]+main[ \t]*)'
    r'(?P<comment>#[^\r\n]*)?(?P<eol>\r?\n)?\Z'
)


def valid_uri(uri):
    return isinstance(uri, str) and (uri == ORIGINAL_URI or bool(MIRROR_URI.fullmatch(uri)))


def source_plan(content, codename, uri):
    """Preserve options/comments; recognize mirrors only with our own exact marker."""
    if not valid_uri(uri):
        raise ValueError('Use the official PHP HTTPS URI or an absolute mirror+file URI ending in .list.')
    output, seen, found = [], set(), False
    for line in content.splitlines(keepends=True):
        match = SOURCE.fullmatch(line)
        if not match or match['suite'] != codename:
            output.append(line)
            continue
        comment, tail = match['comment'] or '', match['tail']
        marked = comment == '# ' + MARKER or comment.endswith(' | ' + MARKER)
        original = match['uri'].rstrip('/') in LEGACY_URIS
        if not original and not (marked and MIRROR_URI.fullmatch(match['uri'])):
            output.append(line)
            continue
        found = found or match['kind'] == 'deb'
        if marked:
            if comment == '# ' + MARKER:
                comment = ''
                # The marker was appended with exactly one separating space.
                tail = tail[:-1] if tail.endswith(' ') else tail
            else:
                comment = comment[:-len(' | ' + MARKER)]
        rendered = match['head'] + uri + tail + comment
        if uri != ORIGINAL_URI:
            rendered += (' | ' if comment else ' # ') + MARKER
        # Deduplicate only identical role entries, never entries with other
        # signing/architecture options or comments.
        if rendered not in seen:
            output.append(rendered + (match['eol'] or ''))
            seen.add(rendered)
    rewritten = ''.join(output)
    return {'found': found, 'changed': rewritten != content, 'content': rewritten}


def main():
    from ansible.module_utils.basic import AnsibleModule

    module = AnsibleModule(
        argument_spec=dict(
            codename=dict(type='str', required=True),
            uri=dict(type='str', required=True, no_log=True),
            state=dict(type='str', choices=['inspect', 'present'], default='present'),
        ),
        supports_check_mode=True,
    )
    codename, uri = module.params['codename'], module.params['uri']
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', codename) or not valid_uri(uri):
        module.fail_json(msg='Invalid PHP repository URI or Ubuntu codename.')
    path = os.path.join(SOURCE_DIRECTORY, 'ppa_ondrej_php_%s.list' % codename)
    try:
        if os.path.lexists(path):
            if not stat.S_ISREG(os.lstat(path).st_mode):
                module.fail_json(msg='The PHP role source must be a regular file, not a symlink.')
            with open(path, encoding='utf-8', newline='') as source:
                content = source.read()
        else:
            content = ''
        plan = source_plan(content, codename, uri)
        if module.params['state'] == 'inspect':
            module.exit_json(changed=False, found=plan['found'])
        if not plan['found']:
            if module.check_mode:
                module.exit_json(changed=True, found=False)
            if uri == ORIGINAL_URI:
                # Native apt_repository may already have found the unchanged
                # direct source in another file. Do not take ownership of it.
                module.exit_json(changed=False, found=False)
            module.fail_json(msg='Native PHP PPA entry is missing from its role-owned source file; refusing to rewrite another APT file.')
        if plan['changed'] and not module.check_mode:
            descriptor, temporary = tempfile.mkstemp(dir=module.tmpdir)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as source:
                    source.write(plan['content'])
                module.atomic_move(temporary, path, keep_dest_attrs=True)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        module.exit_json(changed=plan['changed'], found=plan['found'])
    except (OSError, UnicodeError):
        module.fail_json(msg='Could not safely read or update the PHP role source file.')


if __name__ == '__main__':
    main()
