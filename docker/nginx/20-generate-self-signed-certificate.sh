#!/bin/sh
set -eu

certificate_directory=/etc/nginx/certs
certificate_path="$certificate_directory/miyp-selfsigned.crt"
private_key_path="$certificate_directory/miyp-selfsigned.key"
certificate_hostname="${PUBLIC_HOSTNAME:-i7h8}"

mkdir -p "$certificate_directory"

if [ ! -s "$certificate_path" ] || [ ! -s "$private_key_path" ]; then
    echo "Generating a self-signed HTTPS certificate for $certificate_hostname"
    openssl req \
        -x509 \
        -nodes \
        -newkey rsa:2048 \
        -sha256 \
        -days 825 \
        -keyout "$private_key_path" \
        -out "$certificate_path" \
        -subj "/CN=$certificate_hostname" \
        -addext "subjectAltName=DNS:$certificate_hostname,DNS:localhost,IP:127.0.0.1" \
        -addext "keyUsage=digitalSignature,keyEncipherment" \
        -addext "extendedKeyUsage=serverAuth"

    chmod 600 "$private_key_path"
    chmod 644 "$certificate_path"
fi
