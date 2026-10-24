from app.main import create_app

# Entry point for uvicorn: `uvicorn app.asgi:app`. Kept separate so importing app.main
# (e.g. in tests) never requires real environment variables.
app = create_app()
