"""Read an explicit main-context PID path without evaluating nginx includes."""
from ansible.errors import AnsibleFilterError


def nginx_pid_directive(config):
    """Require one simple PID argument; never guess the compiled/include default.

    Tokenize comments, quoted strings and blocks so text inside an unrelated
    directive cannot masquerade as the master process's PID directive. PID
    arguments with quotes/escapes are deliberately unsupported: preserving
    their exact effective filename would require nginx's full string parser.
    """
    if not isinstance(config, str):
        raise AnsibleFilterError('The existing nginx configuration must be text.')
    words, token, pids = [], [], []
    depth = 0
    quote = None
    comment = False
    escaped = False
    variable = False

    def finish_word():
        if token:
            words.append(''.join(token))
            token.clear()

    for char in config:
        if comment:
            if char == '\n':
                comment = False
            else:
                continue
        if escaped:
            token.append(char)
            escaped = False
            continue
        if char == '\\':
            token.append(char)
            escaped = True
            continue
        if quote:
            token.append(char)
            if char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            token.append(char)
            quote = char
            continue
        if variable:
            token.append(char)
            if char == '}':
                variable = False
            continue
        if char == '{' and token and token[-1] == '$':
            token.append(char)
            variable = True
            continue
        if char == '#' and not token:
            finish_word()
            comment = True
            continue
        if char in ' \t\r\n':
            finish_word()
            continue
        if char in ';{}':
            finish_word()
            if words and words[0] == 'pid':
                if depth != 0 or char != ';' or len(words) != 2:
                    raise AnsibleFilterError('Unsupported nginx pid directive; require one main-context pid /absolute/path; directive.')
                pids.append(words[1])
            words.clear()
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth < 0:
                    raise AnsibleFilterError('Unbalanced blocks in the existing nginx configuration.')
            continue
        token.append(char)

    if quote or escaped or variable or depth or token or words:
        raise AnsibleFilterError('Incomplete syntax in the existing nginx configuration; cannot preserve its PID path safely.')
    if len(pids) != 1:
        raise AnsibleFilterError('Require exactly one explicit main-context pid directive in the existing nginx.conf; included or compiled PID defaults cannot be inferred safely.')
    return pids[0]


class FilterModule:
    def filters(self):
        return {'nginx_pid_directive': nginx_pid_directive}
