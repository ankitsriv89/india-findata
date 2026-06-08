# =============================================================================
# web/Dockerfile — build the React SPA and serve it with nginx
# =============================================================================
#
# Stage 1 (builder): npm install + vite build → /app/dist
# Stage 2 (runtime): nginx:alpine serves the static files
#
# The nginx config proxies /macro, /markets, /pipeline to the API container
# so the frontend doesn't need CORS configuration in production.

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copy manifests first for layer caching
COPY package.json package-lock.json* ./
RUN npm ci --silent

# Copy source and build
COPY . .

# VITE_API_URL is empty in production — nginx proxies API calls
ENV VITE_API_URL=""
RUN npm run build

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Copy the built SPA
COPY --from=builder /app/dist /usr/share/nginx/html

# Custom nginx config: SPA routing + API proxy
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s \
    CMD wget -qO- http://localhost/health || exit 1
