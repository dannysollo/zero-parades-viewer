FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY viewer.html /usr/share/nginx/html/viewer.html
COPY index.json /usr/share/nginx/html/index.json
COPY flows_index.json /usr/share/nginx/html/flows_index.json
COPY characters.json /usr/share/nginx/html/characters.json
COPY skills.json /usr/share/nginx/html/skills.json
COPY search_index.json /usr/share/nginx/html/search_index.json
COPY chunks /usr/share/nginx/html/chunks
EXPOSE 8080
