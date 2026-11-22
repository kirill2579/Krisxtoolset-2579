# KrisX Ops Ansible Collection

A selected set of Ansible roles for explicit Linux host configuration. The
collection requires **ansible-core 2.19 or newer** on the controller and
managed Linux hosts with Python and the privileges needed by each role.

| Role | Purpose and scope |
| --- | --- |
| `krisx.ops.system_update` | Package upgrades and timezone on Debian/Ubuntu (APT) and Red Hat-family targets (DNF). Defaults to UTC; reboot is opt-in and platform-dependent. |
| `krisx.ops.users` | Local users, groups, public SSH keys, SSH principals and explicit sudo rules on Debian/Red Hat families. Install `sudo` before managing sudo rules. Optional deployment files must be supplied by the caller. |
| `krisx.ops.sshd` | Validate and manage an explicitly supplied OpenSSH server configuration, including optional Match blocks and SSH CA public keys. Keep console access and confirm a fresh login before closing the existing connection. |
| `krisx.ops.php` | Versioned PHP CLI and FPM on Ubuntu 22.04/24.04. Set the desired versions and package source; disable `php_manage_repository` if using the OS repositories or your own managed source. |
| `krisx.ops.nginx` | Install and configure nginx on APT-based Linux. Supply `nginx_vhost_file` and `nginx_conf` explicitly. |
| `krisx.ops.redis` | Configure standalone distro Redis on Ubuntu 24.04 with systemd; loopback only. See the [role guide](roles/redis/README.md) and [standalone example](examples/redis.yml). |
| `krisx.ops.mongodb` | **Experimental:** MongoDB 7.0, exactly three Ubuntu 22.04 amd64 nodes with AVX and caller-supplied TLS and secrets. Not a single-node installer and not for Ubuntu 24.04. |
| `krisx.ops.pkg_repo` | Manage explicit APT repositories with scoped signing keys and required key checksums. |
| `krisx.ops.pkg_install` | Install explicitly listed packages; an empty list makes no package changes. |

## Install from a checkout

Run these commands from the repository root:

```sh
ansible-galaxy collection build
ansible-galaxy collection install ./krisx-ops-0.1.1.tar.gz
```

Ansible installs the declared `ansible.posix` and `community.general`
dependencies. If the controller is offline, make both available locally.
Use fully qualified role names as in the table above.

## Before applying

- Supply your own inventory and variables. The playbook in
  [examples/web.yml](examples/web.yml) is an Ubuntu 24.04 smoke test with a
  reserved example hostname. It installs PHP 8.3, a loopback Redis service for
  the sample pool, and nginx with a static response. It does not include a PHP
  application, accounts, or certificates.
- Start with a disposable host. Run
  `ansible-playbook -i inventory.yml examples/web.yml --syntax-check`,
  then target a single test host before a broader rollout.
- Run `pkg_repo` before `pkg_install` when the packages come from an
  additional repository. Verify the repository signing key fingerprint and
  the checksum of its exact key file independently before setting `key_checksum`.
- `users` and `sshd` are not coupled. Verify the new account and SSH login
  before switching authentication in `sshd`. Supply deployment scripts only
  via your own `users_deploy_files` directory if you opt in to that feature.
- The bundled PHP pool template uses Redis sessions. Supply a reachable Redis
  endpoint and the matching PHP Redis extension, or provide your own pool template.
- For `mongodb`, start with its read-only `mongodb_action: validate` on
  the intended three hosts. The role rejects Ansible check mode. Set
  `mongodb_members`, `mongodb_replica_set`, `mongodb_bind_ip`, TLS file
  paths, and the shared keyfile and admin credentials using your own
  secured variables. Do not run install on an existing MongoDB host.

Each role's `roles/<role>/defaults/main.yml` lists its defaults. Keep actual
inventory, credentials, hostnames, and private keys in your own project.
