"""Build a byte-preserving, symlink-free controller manifest for nginx files."""
import hashlib
import os
import stat

from ansible.errors import AnsibleFilterError


def nginx_managed_directories(paths):
    """Include intermediate directories beneath the supplied managed roots.

    Ancestors outside those roots are not managed or chmodded by this role.
    Sorting by depth ensures that parent directories are handled first.
    """
    directories = set(paths)
    for path in list(directories):
        parent = os.path.dirname(path)
        while parent != '/' and any(
                parent == root or parent.startswith(root + '/')
                for root in paths):
            directories.add(parent)
            parent = os.path.dirname(parent)
    return sorted(directories, key=lambda path: (path.count('/'), path))


def nginx_static_manifest(source_dir, config_dir):
    """Read every regular source file before any target mutation.

    The manifest contains source paths and SHA-1 checksums, never decoded file
    contents. ansible.builtin.copy transfers the original bytes and verifies
    the checksum. Directory descriptors and O_NOFOLLOW also reject entries
    replaced by symlinks while this controller-side traversal is in progress.
    """
    if not isinstance(source_dir, str) or not source_dir:
        raise AnsibleFilterError('nginx_files_dir must name a controller directory.')
    if not isinstance(config_dir, str) or not os.path.isabs(config_dir):
        raise AnsibleFilterError('nginx_config_dir must be an absolute path.')
    source_dir = os.path.abspath(source_dir)
    files = []
    directories = [config_dir]
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def visit(directory_fd, relative):
        with os.scandir(directory_fd) as entries:
            entries = sorted(entries, key=lambda entry: entry.name)
        for entry in entries:
            child = os.path.join(relative, entry.name)
            source = os.path.join(source_dir, child)
            destination = os.path.join(config_dir, child)
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child_fd = os.open(entry.name, directory_flags, dir_fd=directory_fd)
                try:
                    directories.append(destination)
                    visit(child_fd, child)
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(info.st_mode):
                # O_NONBLOCK avoids hanging on a regular file replaced by a FIFO.
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                file_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                with os.fdopen(file_fd, 'rb') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise AnsibleFilterError(
                            'nginx static sources must be regular files: ' + source)
                    digest = hashlib.sha1()
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                files.append({'src': source, 'dest': destination,
                              'checksum': digest.hexdigest()})
            else:
                raise AnsibleFilterError(
                    'nginx static sources must not be symlinks or non-regular files: ' + source)

    try:
        root_fd = os.open(source_dir, directory_flags)
        try:
            visit(root_fd, '')
        finally:
            os.close(root_fd)
    except OSError as error:
        raise AnsibleFilterError(
            'Cannot read nginx static files from %s: %s' % (source_dir, error)) from error
    return {'files': sorted(files, key=lambda item: item['dest']),
            'directories': nginx_managed_directories(directories)}


class FilterModule:
    def filters(self):
        return {'nginx_static_manifest': nginx_static_manifest,
                'nginx_managed_directories': nginx_managed_directories}
