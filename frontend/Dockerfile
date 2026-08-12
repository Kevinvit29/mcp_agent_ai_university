# Vite 8 requires Node 22.12+ (or Node 20.19+). Node 22 prevents an
# engine mismatch across Mac Apple Silicon and Linux Docker builders.
FROM node:22-alpine AS build
WORKDIR /app

# Install Vite explicitly in the build stage. --include=dev prevents external
# npm/NODE_ENV configuration from omitting the frontend build tool.
COPY package.json package-lock.json ./
RUN npm ci --include=dev --registry=https://registry.npmjs.org/ \
    && test -x node_modules/.bin/vite \
    && node_modules/.bin/vite --version

COPY . .
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
