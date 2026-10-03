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
