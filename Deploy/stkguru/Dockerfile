FROM node:22-alpine AS builder

WORKDIR /app

COPY release/StkGuru/package.json release/StkGuru/package-lock.json ./
RUN npm ci --ignore-scripts

COPY release/StkGuru/ .

# Remove demo data before build to save time/space (real API is proxied via nginx)
RUN rm -rf public/api

RUN npm run build:docker

# ---

FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
