# Campus Whispers 🤫

An anonymous rumor/confession board for your college class.
Classmates post **anonymously** (no login, no name, no IP stored).
Only **you** (the admin) can log in and see / delete everything.
All data lives in a single SQLite file on your server.

Built with the **test-driven-development** skill — 10 passing tests.

## Run it locally

```bash
cd campus-whispers
python -m venv venv
venv\Scripts\python -m pip install flask pytest
venv\Scripts\python run.py
```

Then open:
- Public board:  http://localhost:5000
- Admin panel:   http://localhost:5000/admin
  - Password: `admin123` (change it — see below)

Classmates on your Wi-Fi reach it at your LAN IP (shown in the server log),
e.g. `http://192.168.x.x:5000`.

## Change the admin password / secret

Set env vars before running (do NOT commit the real password):

```bash
set ADMIN_PASSWORD=your-strong-password
set SECRET_KEY=some-random-string
set DB_PATH=campus_whispers.db
venv\Scripts\python run.py
```

## Tests

```bash
venv\Scripts\python -m pytest -q
```

Covers: anonymous posting, empty-post rejection, public feed (no author
leak), admin login + wrong-password rejection, admin-only dashboard,
delete-requires-login, and page routes.

## Deploy (so classmates anywhere can use it)

Push to GitHub and deploy on **Render** (Free) as a Python web service:
- Build: `pip install flask`
- Start: `python run.py`
- Set `ADMIN_PASSWORD`, `SECRET_KEY`, and `PORT` (Render gives this) as env vars.

## Important

This is for your class's fun/community use. Because posts name real people:
- You (admin) can delete anything — use it.
- Don't use it for bullying, threats, or defamation. Keep it light.
- The delete capability exists precisely so you can pull anything harmful.
