# Alembic Migration Guide

## Prerequisites

1. PostgreSQL is running.
2. `DATABASE_URL` is set in `backend/.env`.
3. Alembic is installed in the project virtualenv.

## Commands

Run from `backend`:

```bash
./venv/bin/alembic -c alembic.ini history
./venv/bin/alembic -c alembic.ini upgrade head
./venv/bin/alembic -c alembic.ini current
```

Create a new migration:

```bash
./venv/bin/alembic -c alembic.ini revision -m "your message"
```

Autogenerate from SQLAlchemy metadata:

```bash
./venv/bin/alembic -c alembic.ini revision --autogenerate -m "your message"
```
