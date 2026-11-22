# Standalone Redis

`krisx.ops.redis` configures and starts the Ubuntu 24.04 distro Redis 7.0
service under systemd. First install `redis-server` and `redis-tools`, for
example with `krisx.ops.pkg_install`. This role does not install packages or
manage HA, clients, repositories, data migration or firewall rules.

| Input | Default | Purpose |
| --- | --- | --- |
| `redis_bind` | `['127.0.0.1']` | Nonempty list of loopback addresses only; `::1` needs IPv6. |
| `redis_port` | `6379` | TCP port as an integer. |
| `redis_config` | `{}` | Explicit Redis directives. Quote YAML scalars such as `'yes'` and `'no'`; lists repeat a directive. |
| `redis_adopt_existing_config` | `false` | Explicit consent to replace an unmanaged configuration, including the package default. |
| `redis_service_enabled` | `true` | Start at boot; the role starts Redis even if boot enablement is off. |
| `redis_lxc_disable_private_users` | `false` | Explicit LXC compatibility exception. Leave off unless required by the target. |

The role writes a complete `redis.conf`, not a merge. Before opting in to
adoption, review and back up the existing configuration and data. Set memory
and persistence for the actual workload. Keep any required credentials in
your own encrypted variables, not in the playbook. A failed restart can
restore the previous configuration and retry once; this does not roll back
data or systemd drop-ins.

See [the standalone example](../../examples/redis.yml). It targets a dedicated
test group and leaves adoption disabled until you explicitly opt in.
