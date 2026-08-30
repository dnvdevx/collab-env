# Mission Control - Phase 1 + 2 (auth + validation + Postgres-ready)

## Setup
```
pip install -r requirements.txt --break-system-packages
```

## Configure your environment
1. Copy .env.example to .env in this same folder
2. Fill in your real Postgres password and port directly inline in DATABASE_URL
   (see the file for the exact format - no separate password/port variables)
3. Generate a real JWT_SECRET_KEY:
   python3 -c "import secrets; print(secrets.token_hex(32))"
4. Make sure .env is in .gitignore (it already is in the provided one) - never commit it

## Run the backend
```
uvicorn main:app --reload
```
API docs at http://localhost:8000/docs
If it starts with no errors, it connected to Postgres successfully.

## Auth flow
1. POST /auth/signup with {name, email, password} -> get back an access_token
2. Use that token on every other request: header `Authorization: Bearer <token>`
3. POST /auth/login to get a new token later (tokens expire after 7 days)

## Validation rules (enforced server-side)
- Email must be valid format
- Password: min 8 chars, not all-numbers, not a common weak password
- Names/team names/feature names: can't be blank
- Comments: can't be blank, max 3000 chars
- Diffs capped at 500,000 chars

## Run the watcher (in your project folder, needs a real token)
```
python watcher.py --feature-id 1 --token "your-access-token" --path .
```

## Files
- models.py    - database schema (7 tables)
- database.py  - DB connection; reads DATABASE_URL from .env, falls back to SQLite if absent
- auth.py      - password hashing (bcrypt) + JWT tokens
- main.py      - FastAPI backend, all endpoints require auth + membership checks
- watcher.py   - local script, sends auth token with every checkpoint
- .env.example - template for your local secrets (copy to .env, never commit .env)
