FROM alpine:3.20

# autossh keeps the SSH tunnel alive and reconnects automatically.
RUN apk add --no-cache autossh openssh-client

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Do not give up if the very first connection attempt fails.
ENV AUTOSSH_GATETIME=0

ENTRYPOINT ["/entrypoint.sh"]
