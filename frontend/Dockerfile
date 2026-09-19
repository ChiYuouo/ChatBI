# ChatBI 前端镜像（Vite 构建 + Nginx 托管）
# 构建上下文为 frontend/ 目录

# ---------- 构建阶段 ----------
FROM node:22-alpine AS builder

WORKDIR /app

# 走国内镜像源，加速 npm ci
RUN npm config set registry https://registry.npmmirror.com

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---------- 运行阶段 ----------
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

# 让前端通过 Nginx 同源反代访问后端（apiBaseUrl=/backend），
# 这样浏览器只访问一个端口，且完全不需要 CORS。
RUN printf 'window.CHATBI_CONFIG = { apiBaseUrl: "/backend" };\n' > /usr/share/nginx/html/config.js

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
