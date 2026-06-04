FROM nginx:alpine

# Create directory for SSL
RUN mkdir -p /etc/nginx/ssl

# Copy config and site files
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY server.crt /etc/nginx/ssl/server.crt
COPY server.key /etc/nginx/ssl/server.key
COPY . /usr/share/nginx/html

EXPOSE 80 443
