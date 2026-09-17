#!/bin/bash
set -e

mkdir -p /run/sshd
ssh-keygen -A >/dev/null 2>&1 || true

# Bastion misconfiguration: from the mgmt-net segment, only SSH (22) reaches
# this host. Squid (3128) and Redis (6379) stay reachable only from
# internal-net, which mgmt-net has no route to in the first place -- this
# rule is defense in depth against that assumption ever changing. Port 22
# itself is intentionally left open to any source on mgmt-net (no IP
# allowlist): that's the bastion misconfiguration this lab demonstrates.
MGMT_SUBNET="172.28.98.0/24"
# Flush first: `docker stop`+`start` (as opposed to recreate) re-runs this
# entrypoint against the same container filesystem, so without this the
# rules below would just pile up a duplicate ACCEPT/DROP pair every restart.
iptables -F INPUT
iptables -A INPUT -s "$MGMT_SUBNET" -p tcp --dport 22 -j ACCEPT
iptables -A INPUT -s "$MGMT_SUBNET" -j DROP

# Same restart issue as above: Squid's pidfile survives a stop/start cycle
# on the same container even though the process behind it doesn't, so a
# stale one makes Squid refuse to start ("Found fresh instance PID file").
rm -f /run/squid.pid

# Squid drops its own privileges internally -- only sshd needs to stay root.
squid -N -f /etc/squid/squid.conf &

# Redis never runs as root: it's launched as its own low-privileged account.
su -s /bin/sh redisuser -c "redis-server /etc/redis/redis.conf" &

exec /usr/sbin/sshd -D -e
