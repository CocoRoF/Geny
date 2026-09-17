# ── Build stage ────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# The build context is the REPO ROOT, not frontend/: the chat model in
# shared/ is rendered by this page and by the desktop app, and an image built
# from frontend/ alone cannot see it.
# Install deps first (layer cache)
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

# Copy source
COPY frontend/ ./
# src/shared is a symlink to ../../shared for local development; in the image
# it is the real thing, copied in.
RUN rm -rf src/shared
COPY shared/ ./src/shared/

# Set API_URL at build time so Next.js rewrites bake the correct target.
# At runtime, docker-compose sets API_URL=http://backend:8000 which
# next.config.ts reads via process.env — works for both build & runtime.
ARG API_URL=http://backend:8000
ENV API_URL=${API_URL}

# NEXT_PUBLIC_API_URL must be set at BUILD time (Next.js inlines NEXT_PUBLIC_*
# into the client bundle). Empty string = use relative URLs through nginx.
ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Build Next.js
RUN npm run build

# ── Runtime stage ─────────────────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

# Non-root user
RUN addgroup --system --gid 1001 geny && \
    adduser  --system --uid 1001 geny

# Copy only production artifacts from builder
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./next.config.ts
COPY --from=builder /app/tsconfig.json ./tsconfig.json

USER geny

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
ENV API_URL=http://backend:8000

CMD ["npm", "run", "start"]
