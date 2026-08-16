FROM debian:13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      postgresql-client \
      openssh-client \
      openssl \
 && rm -rf /var/lib/apt/lists/*

COPY seed.sh /usr/local/bin/seed.sh
RUN chmod +x /usr/local/bin/seed.sh
ENTRYPOINT ["/usr/local/bin/seed.sh"]
