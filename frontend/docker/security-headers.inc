# The browser-side defences. In AWS the same headers are set by a CloudFront response-headers policy (Terraform).
# This file is `include`d in every location that sets its own headers, because in nginx a location with ANY
# add_header silently drops the ones inherited from the server block.
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "no-referrer" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
# Only our own origin may supply scripts, styles and API connections; nothing may frame the portal.
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
