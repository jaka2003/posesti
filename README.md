# Posesti Monitor

Spremlja [nepremicnine.net](https://www.nepremicnine.net) za nova zemljišča na Gorenjskem do 300.000 €. Ob novem oglasu pošlje push obvestilo preko [ntfy.sh](https://ntfy.sh).

## Setup na Ubuntu (22.04+)

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
git clone <REPO_URL> ~/posesti
cd ~/posesti
./install.sh
nano .env       # nastavi NTFY_TOPIC
crontab -e      # dodaj: */20 * * * * /home/USER/posesti/run.sh >> /home/USER/posesti/run.log 2>&1
```

## Setup na Windows

1. `python -m pip install curl_cffi beautifulsoup4`
2. Kopiraj `.env.example` → `.env`, nastavi `NTFY_TOPIC`
3. Registriraj scheduled task:
   ```
   schtasks /Create /TN NepremicnineMonitor /TR "<full-path>\run.bat" /SC MINUTE /MO 20 /F
   ```

## Obvestila

V `.env` nastavi enega:
- `NTFY_TOPIC` — push na telefon (ntfy app, brezplačno, naloži iz Play Store/App Store)
- `TG_BOT_TOKEN` + `TG_CHAT_ID` — Telegram
- `SMTP_USER` + `SMTP_PASS` + `MAIL_TO` — email (Gmail App Password)

Skripta uporabi prvo nastavljeno možnost.

## Datoteke

- `monitor.py` — glavna skripta
- `run.sh` / `run.bat` — launcherji za cron / Task Scheduler
- `seen.json` — stanje (kateri oglasi so že bili)
- `monitor.log` — log
