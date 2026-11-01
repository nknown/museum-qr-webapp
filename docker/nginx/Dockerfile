FROM nginx:alpine

RUN apk add --no-cache openssl

COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY 20-generate-self-signed-certificate.sh /docker-entrypoint.d/20-generate-self-signed-certificate.sh

RUN chmod +x /docker-entrypoint.d/20-generate-self-signed-certificate.sh
