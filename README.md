# Mission Control - Phase 1

## Setup
```
pip install -r requirements.txt --break-system-packages
```

## Run the backend
```
uvicorn main:app --reload
```
API docs at http://localhost:8000/docs

## Run the watcher (in a separate terminal, inside your project folder)
```
python watcher.py --feature-id 1 --path .
```
The folder you point --path at must be a git repo.

## Files
- models.py    - database schema (7 tables)
- database.py  - DB connection (SQLite locally, swap DATABASE_URL for Postgres later)
- main.py      - FastAPI backend, all API endpoints
- watcher.py   - local script that posts checkpoints on file save
