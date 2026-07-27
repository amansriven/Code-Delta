web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker: python -m procrastinate --app app.procrastinate_app.procrastinate_app worker
release: python -m procrastinate --app app.procrastinate_app.procrastinate_app schema --apply
