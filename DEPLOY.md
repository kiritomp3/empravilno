# Deploy on Ubuntu

## 1. Prepare the server

```bash
sudo apt update
sudo apt install -y ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
sudo systemctl enable docker
sudo systemctl start docker
```

Open only the ports you really need:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 2. Upload the project

```bash
git clone <YOUR_REPOSITORY_URL> /opt/emgood
cd /opt/emgood
cp .env.example .env
```

Fill `.env` with real values.

Minimum required variables:

```env
BOT_TOKEN=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
REDIS_URL=redis://redis:6379/0
LOG_LEVEL=INFO
ADMIN_TOKEN=very-long-random-string
ADMIN_CHAT_IDS=123456789
YOOMONEY_RECEIVER=4100...
YOOMONEY_SECRET=...
YOOMONEY_SUCCESS_URL=https://bot.example.com/payment/success
YOOMONEY_FAIL_URL=https://bot.example.com/payment/fail
# Только для старых ссылок оплаты без суффикса тарифа (sub_<chat_id>).
# Новые тарифы: неделя 50 ₽ / 7 дн., год 2500 ₽ / 365 дн. — зашиты в коде.
SUBSCRIPTION_PRICE=10
SUBSCRIPTION_DAYS=30
```

## 3. Start the containers

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f bot
```

The app should answer on:

- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/readyz`
- `http://127.0.0.1:8000/metrics`
- `http://127.0.0.1:8000/webhooks/yoomoney/notify`

Protected stats endpoint:

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" http://127.0.0.1:8000/stats
```

## 4. Put HTTPS in front

For ЮMoney notifications you need a public HTTPS endpoint. The simplest production setup is Nginx as reverse proxy.

Install Nginx:

```bash
sudo apt install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

Example config `/etc/nginx/sites-available/emgood`:

```nginx
server {
    server_name bot.emgood.ru;

    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/emgood /etc/nginx/sites-enabled/emgood
sudo nginx -t
sudo systemctl reload nginx
```

Issue a Let's Encrypt certificate:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d bot.example.com
```

After that, set the webhook URL in ЮMoney to:

```text
https://bot.example.com/webhooks/yoomoney/notify
```

## 5. Restart and update

Restart:

```bash
cd /opt/emgood
docker compose up -d --build
```

Update:

```bash
cd /opt/emgood
git pull
docker compose up -d --build
```

## 6. What survives reboots

- Docker is enabled with `systemctl enable docker`
- Containers use `restart: unless-stopped`
- Redis data is stored in Docker volume `redis-data`

That means the bot, profiles, logs and subscription dates should survive server reboot.

## 7. Basic production checklist

- Rotate and protect all secrets
- Keep `.env` only on the server
- Use HTTPS for ЮMoney webhook
- Watch `docker compose logs -f bot`
- Check `/healthz` and `/readyz` after each deploy
- Scrape `/metrics` from your monitoring system
- Use `/stats` in Telegram only from chats listed in `ADMIN_CHAT_IDS`
