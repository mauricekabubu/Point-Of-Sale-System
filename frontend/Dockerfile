FROM nginx:1.27-alpine

RUN rm -f /etc/nginx/conf.d/default.conf

COPY frontend/nginx/default.conf /etc/nginx/conf.d/default.conf

COPY frontend/ /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]