# README.md

This directory contains the runtime / infrastructure configuration for imladris.

Start, restart, stop with:

Can hide the terminal control chars with:

```
docker compose --no-ansi up -d
```

```
docker compose restart
```

Or if you want to see config changes picked up cleanly (restart doesn't re-read volume mounts on all platforms):

```
docker compose down && NO_COLOR=1 docker compose up -d
```

Or just individual containers, e.g.

```
docker compose up -d pacs-proxy ohif
```


# Useful docker commands

## Inspect logs

```
docker logs imladris-pacs 2>&1 | grep -i "error\|transfer\|syntax" | tail -20
```


## Look for a file in a container image.

```
docker exec imladris-ohif find /usr/share/nginx/html -name "*.bundle.*js" | grep -i video
```

