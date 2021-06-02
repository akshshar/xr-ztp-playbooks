FROM debian:stable-slim
LABEL maintainer="akshshar"
LABEL description="ISC DHCP Server and NGINX on debian slim"


RUN apt-get update && apt-get install -y supervisor isc-dhcp-server nginx net-tools iproute2 vim

RUN mkdir /config /data

COPY overlay/ /
RUN chmod 755 /entrypoint.sh 
COPY supervisor.conf /etc/supervisord.conf

VOLUME /config
VOLUME /data

ENTRYPOINT ["/entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
