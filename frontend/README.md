# SAST Findings Explorer (frontend)

A React SPA that visualises the aggregated SAST findings produced by the
pipeline. It runs on the **master node** as a small Docker Compose stack
(React app + nginx + certbot) and reads the finished `mega-artifact.json`
backups straight off the master-node artifacts PV — no extra backend.

## What it does

Progressive **miller-column** navigation, drilling left→right:

```
repo → branch → commit → severity → tool → file → line
```

- **Dynamic top bar** — breadcrumb + per-level filter chips + a search box that
  re-scopes as you descend (repo filters: recent commit / most findings /
  highest severity / most runs; branch: authors / most severity / oldest /
  active; commit: newest / pipeline status / new / resolved; etc.).
- **Line-open split view** — opening an individual finding (the last node)
  snaps the columns into a narrow left rail and shows the finding + supporting
  data (rule, fingerprint, CVSS, fixed version, effort, deep link to the source
  tool, recommended action) on the right half.
- **Metric cards** — active / critical / auto-resolved / runs, scoped to the
  current selection.

## Smart delete (the MVP rule)

A finding is **active** on a branch only while its fingerprint is present in the
branch's **latest** commit. When a newer commit stops reporting a fingerprint an
older commit had, that finding is auto-removed from the active tree and retained
only in **resolved history** (toggle in the top bar). Per commit,
`resolved(C) = fingerprints in C's parent that are absent from C`.

Implemented in [`src/data/smartDelete.js`](app/src/data/smartDelete.js) as a
pure, framework-free function. Unit test:

```bash
cd app && npm run test:smartdelete
```

## Data source

nginx serves the artifacts PV at `/artifacts/` with `autoindex_format json`:

```
GET /artifacts/                              -> [{name, type:"directory"}, ...]
GET /artifacts/{job_id}/mega-artifact.json   -> a v3.0.0 artifact
```

The data layer ([`src/data/loadArtifacts.js`](app/src/data/loadArtifacts.js))
fetches the listing, pulls every artifact, builds the tree and applies smart
delete client-side. If `/artifacts` is unreachable or empty it falls back to
bundled sample data so the UI always renders.

## Run it

```bash
cp .env.example .env          # set DOMAIN, LETSENCRYPT_EMAIL, ARTIFACTS_DIR
#   ARTIFACTS_DIR -> host path of the master PV backup dir
#                    (e.g. /data/sast-artifacts-backup)

# HTTP only (local / no domain):
docker compose up -d --build frontend nginx
#   open http://localhost/

# With TLS (real domain pointing at this node):
./certbot/init-letsencrypt.sh   # seeds a cert, issues a real one, reloads nginx
docker compose up -d            # brings up the certbot auto-renew loop too
```

nginx reverse-proxies `:80` and `:443` onto the React app's `:3000`, serves
`/artifacts` from the PV, answers ACME challenges, and terminates TLS.
Set `STAGING=0` in `.env` once you've confirmed staging certs issue cleanly.

## Layout

```
frontend/
├── app/                    React (Vite) SPA
│   ├── src/
│   │   ├── data/           loadArtifacts, smartDelete (+ test), sampleData, util
│   │   ├── hooks/          useExplorer (miller-column state machine)
│   │   ├── components/     MetricCards, TopBar, Columns, DetailPanel
│   │   └── App.jsx
│   └── Dockerfile          build → serve static on :3000
├── nginx/templates/        default.conf.template (envsubst ${DOMAIN} only)
├── certbot/                init-letsencrypt.sh + cert volumes
└── docker-compose.yml
```
