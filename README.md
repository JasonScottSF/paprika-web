# paprika-web

A read-only web frontend for [Paprika 3](https://www.paprikaapp.com/) that serves your local recipe library from a browser. Matches the dark UI of the Mac app.

## Features

- Browse recipes by category, sorted by name or rating
- List and grid views with thumbnail photos
- Full-text search (HTMX, no page reload)
- Clickable ingredients — see every recipe that uses one
- **Find by Ingredient** — enter what you have, get ranked suggestions weighted by your Paprika ratings (requires 3+ ingredients including a meat and a vegetable)

## Architecture

Paprika 3 stores its data in a SQLite database on your Mac. This app runs on a Linux server and reads a synced copy of that database. The Mac pushes updates to the server on a schedule via rsync.

```
Mac (Paprika 3) ──rsync──▶ Linux server (Docker) ──▶ browser
```

## Server setup

### 1. Clone and configure

```bash
git clone https://github.com/JasonScottSF/paprika-web.git
cd paprika-web
echo "PAPRIKA_DATA_DIR=/opt/paprika-data" > .env
```

### 2. Sync data from Mac (first time)

Run this on the Mac, substituting your server's IP and username:

```bash
rsync -avz ~/Library/Group\ Containers/72KVKW69K8.com.hindsightlabs.paprika.mac.v3/Data/ user@server-ip:/opt/paprika-data/
```

### 3. Start the container

```bash
sudo docker compose up -d --build
```

### 4. Nginx Proxy Manager

In NPM, add a Proxy Host:

| Setting | Value |
|---------|-------|
| Domain | your domain |
| Scheme | `http` |
| Forward Hostname | server IP or hostname |
| Forward Port | `5007` |

Enable Let's Encrypt SSL on the SSL tab.

## Keeping data in sync

Add a cron job on the Mac to push updates automatically. Run `crontab -e` and add:

```
*/15 * * * * rsync -az ~/Library/Group\ Containers/72KVKW69K8.com.hindsightlabs.paprika.mac.v3/Data/ user@server-ip:/opt/paprika-data/ --delete
```

This syncs every 15 minutes. The Mac must be on and awake for the sync to run.

To verify the cron is registered:

```bash
crontab -l
```

## Updating the app

On the server:

```bash
cd ~/paprika-web
git pull origin main
sudo docker compose up -d --build
```

## Tech stack

- Python / FastAPI + Jinja2 + HTMX
- Paprika 3 SQLite database (read-only)
- Docker
