#!/bin/sh
# Replace API_URL_PLACEHOLDER with actual API_URL environment variable
sed -i "s|API_URL_PLACEHOLDER|${API_URL}|g" /etc/nginx/conf.d/default.conf

# Start nginx
exec nginx -g "daemon off;"
