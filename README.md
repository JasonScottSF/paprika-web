# paprika-web

A read-only web frontend for [Paprika 3](https://www.paprikaapp.com/) that serves your local recipe library from a browser. Matches the dark UI of the Mac app.

## Features

- Browse recipes by category, sorted by name, rating, or date added
- List and grid views with thumbnail photos
- Full-text search (HTMX, no page reload)
- Favorites filter
- Clickable ingredients — see every recipe that uses one
- **Find by Ingredient** — enter what you have, get ranked suggestions weighted by your Paprika ratings (requires 3+ ingredients including a meat and a vegetable)
- Meal planner and grocery list views

## Requirements

- Docker
- Paprika 3 installed on the same Mac (the app reads its SQLite database directly)
- Nginx Proxy Manager on the same Docker host (for reverse proxy / SSL)

## Deploy

```bash
git clone https://github.com/JasonScottSF/paprika-web.git
cd paprika-web
docker compose up -d --build
```

The Paprika data directory is auto-detected from the default macOS Group Container path. No configuration needed on a standard install.

### Custom data path

If your Paprika data lives elsewhere, set `PAPRIKA_DATA_DIR` before running:

```bash
PAPRIKA_DATA_DIR=/path/to/paprika/Data docker compose up -d --build
```

## Nginx Proxy Manager setup

The container joins the `nginx-dashboard_dashboard_net` Docker network and is reachable by container name. In NPM, add a Proxy Host:

| Setting | Value |
|---------|-------|
| Domain | your domain |
| Scheme | http |
| Forward Hostname | `paprika-web` |
| Forward Port | `5007` |

Enable Let's Encrypt SSL on the SSL tab.

## Updating

```bash
git pull origin main
docker compose up -d --build
```

## Tech stack

- Python / FastAPI + Jinja2 + HTMX
- Paprika 3 SQLite database (read-only)
- Docker
