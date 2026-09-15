FROM alpine:3.20

RUN apk add --no-cache redis squid curl

COPY squid.conf /etc/squid/squid.conf
COPY redis.conf /etc/redis.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 3128 6379
ENTRYPOINT ["/entrypoint.sh"]
