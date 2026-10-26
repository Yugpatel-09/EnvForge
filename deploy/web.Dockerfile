FROM node:24-alpine AS build
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci --include=optional
COPY apps/web/ ./
RUN npm run build
FROM nginxinc/nginx-unprivileged:stable-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
