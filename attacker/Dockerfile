FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl openssh-client python3 python3-requests redis-tools netcat-openbsd ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
CMD ["sleep", "infinity"]
