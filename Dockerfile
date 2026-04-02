FROM python:3.12-slim

# Install system deps
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install Poetry to /usr/local (accessible by all users)
ENV POETRY_HOME="/usr/local"
RUN curl -sSL https://install.python-poetry.org | python3 -

# Create non-root user (required: claude CLI refuses --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash appuser

# Copy the app code and give ownership to appuser
COPY --chown=appuser:appuser . /app
WORKDIR /app

# Keep virtualenv inside the project dir so it survives the USER switch
ENV POETRY_VIRTUALENVS_IN_PROJECT=true

# Install as appuser so the venv is owned by appuser
USER appuser
RUN poetry install --no-root

EXPOSE 8000
CMD ["poetry", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
