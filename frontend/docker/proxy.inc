# Shared by every API location. $up is set by the location. No URI part on proxy_pass means the original
# request path and query string are forwarded unchanged.
proxy_pass $up;
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
# Keep the caller's request id so one id traces browser -> proxy -> service. Create one if the browser sent none.
proxy_set_header X-Request-ID $http_x_request_id;
proxy_connect_timeout 3s;
proxy_read_timeout 30s;
