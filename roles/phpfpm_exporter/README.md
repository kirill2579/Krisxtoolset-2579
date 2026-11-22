# PHP-FPM exporter

`krisx.ops.phpfpm_exporter` installs a checksum-pinned
[Lusitaniae/phpfpm_exporter](https://github.com/Lusitaniae/phpfpm_exporter)
release on Debian/Ubuntu with systemd. It runs as a separate unprivileged
service. It does not configure PHP-FPM or Prometheus.

- Prepare PHP-FPM and set `pm.status_path = /status` first. When provisioning
  PHP in the same play, flush its handlers before starting the exporter.
- Load the same `php_fpm_conf` and `php_fpm_socket_dir` variables for the
  exporter to derive its sockets from the configured pools. Alternatively
  set `phpfpm_exporter_socket_paths` and
  `phpfpm_exporter_socket_groups` explicitly. Use the existing groups
  permitted to access the sockets; the role does not change socket ownership.
- Metrics default to `127.0.0.1:9223/metrics`. If scraping remotely, choose
  a reachable listen address and restrict access to trusted scrapers.
  The role does not configure TLS, authentication or firewall rules.
- The inherited default is upstream 0.5.0 with pinned amd64/arm64 digests.
  Other releases require an explicit trusted SHA-256 digest for that archive.

See [the standalone example](../../examples/phpfpm_exporter.yml). After
configuration, check `curl -fsS http://127.0.0.1:9223/metrics` on the target;
an unavailable pool reports `php_fpm_up 0` for its socket.
