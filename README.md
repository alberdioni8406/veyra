# Veyra V0

Rentable temporary social spaces. Pay with Bitcoin Cash. Meet your people.

Built for deployment on **Vercel** with an external **Postgres** database (Neon recommended).

## Features

- Rent a timed digital room (text chat)
- Host pays rental fee in BCH; can charge entry fee
- Public discovery directory
- Lightweight profiles + connections
- Host controls (close, kick, dashboard)
- Admin economic overview
- Payment abstraction ready for more chains later

## Stack

- FastAPI + Jinja2
- SQLAlchemy + Postgres (Neon / any Postgres)
- BCH payment verification (test mode available)
- Chat via polling (Vercel-friendly; no WebSockets required)

## Local development

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env – for local you can keep SQLite:
# DATABASE_URL=sqlite:////tmp/veyra.db
# PAYMENT_TEST_MODE=true
# SECRET_KEY=dev-secret

uvicorn main:app --reload --port 8000
```

Open http://127.0.0.1:8000

Default admin (only created when the DB is empty):

- Username: value of `ADMIN_USERNAME` (default `admin`)
- Password: value of `ADMIN_PASSWORD` (default `change-me-now`)

**Change these before production.**

## Deploy on Vercel

1. Create a Postgres database on [Neon](https://neon.tech) (or any Postgres host).
2. Push this repo to GitHub.
3. Import the project in [Vercel](https://vercel.com).
4. Framework Preset: **Other**.
5. Add environment variables (see below).
6. Deploy.

### Required environment variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Long random string (`openssl rand -hex 32`) |
| `DATABASE_URL` | Neon / Postgres connection string (include `?sslmode=require`) |
| `BCH_RECEIVING_ADDRESS` | Your Bitcoin Cash address |
| `PAYMENT_TEST_MODE` | `false` in production |
| `ADMIN_PASSWORD` | Strong password for the first admin user |
| `ADMIN_USERNAME` | Optional, default `admin` |

Optional:

- `PLATFORM_ROOM_FEE_PERCENT` (default 10)
- `PLATFORM_ENTRY_FEE_PERCENT` (default 5)
- `MINIMUM_ROOM_PRICE`
- `BASE_RENTAL_PER_HOUR`

## Project structure

```
veyra/
├── main.py              # App + routes
├── models.py
├── database.py          # SQLite locally / Postgres in production
├── auth.py
├── schemas.py
├── config.py
├── services/payment.py  # BCH adapter (extensible)
├── templates/           # Mobile-first UI
├── requirements.txt
├── vercel.json
└── .env.example
```

## Notes for Vercel

- Chat uses **polling** (every ~2.5s) so it works without persistent WebSockets.
- Database must be external Postgres; SQLite is only for local demos.
- Cold starts are normal on the free tier; first request after idle may be slower.

## License

Private / all rights reserved until stated otherwise.
