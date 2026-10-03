# Changelog

## Unreleased

### Added

- Initial release: Vela as a first-class ServerKit extension. Create, list
  and manage named Vela instances from a new Vela page in the panel nav;
  each instance deploys from the official Vela `serverkit.yaml` recipe as a
  ServerKit managed app with its own container, 4 GB data disk (daily
  backups, 7 retained), domain and generated first-start password in the
  secret vault.
- Instance API under `/api/v1/vela`: list/detail reads accept a JWT or a
  scoped API key (`servers:read`); create, delete and start/stop/restart
  require the developer role. Deletes are confirm-gated and run through the
  panel's suspend/purge lifecycle.
- Manager page with instance cards, a create wizard (server picker, name,
  optional domain), an Open button per instance and a "Create your first
  desktop" walkthrough. Frontend ships as a prebuilt runtime ESM bundle.

### Fixed

- Creating a second instance no longer fails with
  `Bind for 0.0.0.0:7700 failed: port is already allocated`. Each instance
  now gets its own host port at create time, allocated through the panel's
  own port allocator (the same seam template installs and WordPress
  environments use), starting from Vela's default 7700. The port is baked
  into the instance's stored manifest — so it stays stable across restarts,
  redeploys and re-applies — and Vela listens on it inside the container via
  `VELA_PORT`.
