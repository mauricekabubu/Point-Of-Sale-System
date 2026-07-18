FROM nginx:1.27-alpine
 
# Remove default config, use our own
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
 
# Copy static site files (html, css, js)
COPY frontend/ /usr/share/nginx/html
 
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
