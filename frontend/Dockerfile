# syntax=docker/dockerfile:1
# LOCAL / DEMO ONLY. In AWS the frontend is NOT a container: `npm run build` produces static files that go to S3 and
# are served by CloudFront (see ADR 0001, D1). This image exists so the whole platform runs with one `docker compose up`.
# nginx stands in for both CloudFront (static files + security headers) and the ALB (path routing to the services).

FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Tests run as part of the build: failing tests fail the image.
RUN npm test && npm run build
# Source maps are for an error-tracking tool, not for the public web server.
RUN find dist -name '*.map' -delete

FROM nginxinc/nginx-unprivileged:1.27-alpine
# The "unprivileged" variant runs as a non-root user and listens on 8080.
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/security-headers.inc /etc/nginx/snippets/security-headers.inc
COPY docker/proxy.inc /etc/nginx/snippets/proxy.inc
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
