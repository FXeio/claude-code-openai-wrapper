FROM python:3.12-slim

# Install system deps (curl for Poetry installer)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry to /usr/local (accessible by all users)
ENV POETRY_HOME="/usr/local"
RUN curl -sSL https://install.python-poetry.org | python3 -

# Note: Claude Code CLI is bundled with claude-agent-sdk >= 0.1.8
# No separate Node.js/npm installation required

# Create non-root user (required: claude CLI refuses --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash appuser

# Copy the app code
COPY . /app

# Set working directory
WORKDIR /app

# Install Python dependencies with Poetry (as root, before switching user)
RUN poetry install --no-root

# Give appuser ownership of app and poetry virtualenv
RUN chown -R appuser:appuser /app /root/.cache/pypoetry
USER appuser

# Expose the port (default 8000)
EXPOSE 8000

# Run the app with Uvicorn (development mode with reload; switch to --no-reload for prod)
CMD ["poetry", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
