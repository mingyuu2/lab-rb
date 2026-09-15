#!/bin/sh
set -e

mkdir -p /var/log/redis /data
touch /var/log/redis/redis.log

# busybox crond watches /etc/crontabs/<username>; skips unparseable lines so
# Redis RDB binary garbage surrounding the injected cron entry won't block it.
crond

# Squid drops its own privileges internally -- only Redis needs to stay root.
squid -N -f /etc/squid/squid.conf &

# No USER directive in this image: invoking redis-server directly (not via a
# service wrapper that would drop privileges) keeps it -- and files it writes
# to disk -- running as root.
exec redis-server /etc/redis.conf
