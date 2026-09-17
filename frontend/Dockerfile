FROM caddy:2-alpine

# Build context is frontend/ only - nothing from backend/ is needed or copied.
COPY Caddyfile /etc/caddy/Caddyfile
COPY index.html auth.html dashboard.html new-request.html request.html /srv/
COPY styles.css app.js core.js config.js /srv/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8080

# Railway injects PORT; Caddy binds it via the Caddyfile.
CMD ["/usr/local/bin/entrypoint.sh"]
