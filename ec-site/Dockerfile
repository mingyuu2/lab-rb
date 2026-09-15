# ---- stage 1: build Tailwind CSS locally (no CDN at runtime) ----
FROM node:20-slim AS assets
WORKDIR /build
COPY package.json ./
RUN npm install
COPY tailwind.config.js postcss.config.js ./
COPY static/src ./static/src
COPY templates ./templates
RUN npx tailwindcss -i ./static/src/input.css -o ./static/css/style.css --minify

# ---- stage 2: runtime ----
FROM python:3.11-slim AS runtime
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=assets /build/static/css/style.css ./static/css/style.css
EXPOSE 80
CMD ["python", "app.py"]
