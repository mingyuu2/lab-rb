FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
      squid redis-server openssh-server iptables sudo python3 \
    && rm -rf /var/lib/apt/lists/*

# Redis runs as its own low-privileged account -- it is never root in this
# lab. The vulnerability is a group-writable SSH home directory, not Redis's
# own privilege level.
RUN groupadd redisgrp \
    && useradd -m -g redisgrp -s /usr/sbin/nologin redisuser \
    && useradd -m -g redisgrp -s /bin/bash proxyuser \
    && mkdir -p /home/proxyuser/.ssh \
    && chown proxyuser:redisgrp /home/proxyuser/.ssh \
    && chmod 2775 /home/proxyuser/.ssh \
    && mkdir -p /home/redisuser/data \
    && chown -R redisuser:redisgrp /home/redisuser

# GTFOBins-style local privesc vector, isolated so it can be swapped later.
COPY sudoers-privesc /etc/sudoers.d/proxy-lab-privesc
RUN chmod 440 /etc/sudoers.d/proxy-lab-privesc

COPY squid.conf /etc/squid/squid.conf
COPY redis.conf /etc/redis/redis.conf
# Ubuntu's redis package locks /etc/redis down to its own "redis" system
# account; our redisuser account needs to read the config from there too.
RUN chmod 755 /etc/redis && chmod 644 /etc/redis/redis.conf
COPY sshd_config /etc/ssh/sshd_config.d/lab.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 3128 6379 22
ENTRYPOINT ["/entrypoint.sh"]
