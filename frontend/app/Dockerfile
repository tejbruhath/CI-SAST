# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

# ---- runtime stage: serve the static SPA on :3000 ----
FROM node:20-alpine AS run
WORKDIR /app
RUN npm install -g serve@14
COPY --from=build /app/dist ./dist
EXPOSE 3000
# SPA fallback so client-side state deep-links don't 404
CMD ["serve", "-s", "dist", "-l", "3000"]
