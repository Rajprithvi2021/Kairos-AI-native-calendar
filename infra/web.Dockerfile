FROM node:26-alpine AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:26-alpine AS build
WORKDIR /app
# Rewrites (/api/* -> FastAPI) are resolved at build time.
ENV NEXT_TELEMETRY_DISABLED=1 KAIROS_API_URL=http://api:8000
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web ./
RUN npm run build

FROM node:26-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 KAIROS_API_URL=http://api:8000
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "start"]
