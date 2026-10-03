# serverkit-vela

A [ServerKit](https://github.com/jhd3197/ServerKit) extension that makes
[Vela](https://github.com/jhd3197/vela) — a personal app server — a
first-class product in the panel nav. Create, list and manage named Vela
instances from the panel: each instance is a virtual server with its own
container, data disk, domain and login.

## Requirements

- A ServerKit panel **1.11.17** or newer.
- A Docker-capable server the panel manages. Phase 1 deploys to the **panel
  host** itself; the create form accepts a `server_id` and validates it, but
  fleet (remote agent) targets are refused with a clear message because the
  panel's manifest apply only runs Dockerfile builds on the panel host today.
- For a usable instance, a domain pointing at the host. Vela refuses to
  start without `VELA_PUBLIC_ORIGIN` and `VELA_TRUSTED_PROXIES`.

## Install

From the panel: **Marketplace → Install from URL** and paste this repository
(`jhd3197/serverkit-vela`), or build a zip with `scripts/build-zip.sh` and use
**Upload Zip**. The panel previews the manifest and shows the declared
permissions (`docker`, `network`, `filesystem`) before anything is installed.

The frontend ships as a prebuilt ESM bundle (`frontend_entry:
dist/index.mjs`), so the page renders on a production panel without a
rebuild. Rebuild it after changing `frontend/`:

```bash
cd frontend && npm install && npm run build   # writes dist/index.mjs
```

## How instances map to managed apps

Creating an instance ("Home" → `vela-home`) runs entirely through the
panel's own serverkit.yaml import path — no raw docker calls:

1. The extension renders the [Vela repo's `serverkit.yaml`](https://github.com/jhd3197/vela/blob/main/serverkit.yaml)
   verbatim with the project, service and disk names templated per instance,
   stores it as the project manifest **with the repo as provenance**, and
   calls `ManifestApplyService.apply` — the same engine behind
   `POST /api/v1/manifests/apply`.
2. The apply creates the managed app (one per instance, in its own project),
   clones the Vela repo, wires the Dockerfile build, sets
   `VELA_DATA_DIR`/`VELA_PUBLIC_ORIGIN`/`VELA_TRUSTED_PROXIES`, generates
   `VELA_INITIAL_PASSWORD` into the **secret vault**, ensures the 4 GB
   `/data` disk and its daily backup policy (7 retained), and attaches the
   domain (vhost + DNS + certificate) when one is given.
3. Each instance gets its own host port, allocated at create time through the
   panel's port allocator (starting from Vela's default 7700) and pinned in
   the stored manifest, so restarts and redeploys keep it. Vela listens on
   the same port inside the container via `VELA_PORT`.
4. The build runs as a normal async deployment job
   (`DeploymentJobService.enqueue_app_deploy`), tracked on the instance and
   visible in the panel's Deploy Activity.

Instance metadata (slug, display name, server, domain, port, managed-app id)
lives in the extension's own plugin store; everything else is ordinary panel
state you can inspect on the Apps, Domains, Backups and Secrets pages.

`VELA_TRUSTED_PROXIES` defaults to `172.17.0.1` (the docker bridge gateway —
where a host nginx proxy appears from inside the container). Adjust it in
the app's env vars if your proxy presents a different address; see Vela's
`docs/SERVER.md`.

## API

All routes are under `/api/v1/vela`. Reads accept a JWT or an `X-API-Key`
with the `servers:read` scope; writes require the developer role.

| Route | Purpose |
|---|---|
| `GET /instances` | List instances with live status and URL |
| `POST /instances` | Create `{server_id?, name, domain?}` → 201 + deploy job id |
| `GET /instances/<slug>` | Detail: status, URL, vault reference, disk/backup info |
| `POST /instances/<slug>/start\|stop\|restart` | Lifecycle via the panel's application lifecycle service |
| `DELETE /instances/<slug>` | Confirm-gated (`?confirm=<slug>`); suspends then purges the managed app, its disk and vhost |

The first-start password is never returned by the API. The detail response
points at it: vault `manifest`, secret `<slug>_vela_initial_password`
(e.g. `vela_home_vela_initial_password`) — reveal it on the panel's Secrets
page. It applies on first start only.

## Security notes

- Read routes are deliberately API-key capable (`servers:read`) so an
  automation can poll instance status with one scoped key; give it nothing
  else. Write routes are JWT/session territory (developer role), matching
  the panel's own app-management routes.
- Deleting an instance removes its container, data disk and domain route
  through the panel's recycle-bin purge — the same path
  `DELETE /api/v1/apps/<id>?purge=true` runs. Backup archives already taken
  are kept.
- Every create/delete/action writes a panel audit-log entry.
- The extension never sees or stores the generated Vela password; it only
  records which vault secret holds it.

## Development

```bash
# Backend compile check
python -m py_compile backend/*.py

# Frontend bundle
cd frontend && npm install && npm run build

# Tests — boot the real panel app from the sibling checkout and skip
# cleanly when it is absent (override with SERVERKIT_BACKEND=...)
python -m unittest discover -s tests
```

## Phase notes

- **Phase 1 (this version):** panel-host deploys, instance registry,
  create/list/detail/delete, start/stop/restart, the manager page and the
  "Create your first desktop" walkthrough.
- **Later:** fleet (remote agent) deploy targets when the panel's remote
  appliance apply lands, domain attach/detach on existing instances, and
  surfacing backup runs in the instance detail.
