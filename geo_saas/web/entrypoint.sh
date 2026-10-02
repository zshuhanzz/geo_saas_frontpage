#!/bin/sh

# If VITE_API_URL is not set, provide a default fallback
if [ -z "$VITE_API_URL" ]; then
  VITE_API_URL="http://localhost:8080"
fi

# If VITE_AGENT_API_URL is not set, provide a default fallback
if [ -z "$VITE_AGENT_API_URL" ]; then
  VITE_AGENT_API_URL="http://localhost:8002"
fi

# Replace placeholders with actual environment variables in nginx conf
sed -i "s|VITE_AGENT_API_URL_PLACEHOLDER|${VITE_AGENT_API_URL}|g" /etc/nginx/conf.d/default.conf
sed -i "s|VITE_API_URL_PLACEHOLDER|${VITE_API_URL}|g" /etc/nginx/conf.d/default.conf

# Start nginx
exec nginx -g "daemon off;"
