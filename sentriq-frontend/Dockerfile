# Build the Vite bundle, then serve it statically with nginx (which also
# reverse-proxies /api to the backend so the SPA is single-origin).
FROM node:20-alpine AS build # Node stage for npm install + vite build
WORKDIR /app # container app root
COPY package.json package-lock.json* ./ # deps manifests first for layer cache
RUN npm install # install frontend dependencies
COPY . . # copy source after install
RUN npm run build # produce dist/ static assets

FROM nginx:1.27-alpine # tiny static file server
COPY nginx.conf /etc/nginx/conf.d/default.conf # SPA + /api proxy config
COPY --from=build /app/dist /usr/share/nginx/html # built assets only
EXPOSE 80 # HTTP port
