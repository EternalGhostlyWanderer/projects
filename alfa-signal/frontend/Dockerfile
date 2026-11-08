FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ARG VITE_USE_DEMO=0
ARG VITE_COMPANY_IDS=SYN_001,SYN_002,SYN_003,SYN_004,SYN_005,SYN_006
ARG VITE_API_URL=
ARG VITE_DEMO_AUTH=0
ARG VITE_LOGIN_HINT=1

ENV VITE_USE_DEMO=${VITE_USE_DEMO} \
    VITE_COMPANY_IDS=${VITE_COMPANY_IDS} \
    VITE_API_URL=${VITE_API_URL} \
    VITE_DEMO_AUTH=${VITE_DEMO_AUTH} \
    VITE_LOGIN_HINT=${VITE_LOGIN_HINT}

RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
