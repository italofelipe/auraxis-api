ARG PYTHON_BASE_IMAGE=public.ecr.aws/docker/library/python:3.13.2-alpine
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Drop root: create and switch to a non-root user (port 3333 > 1024).
RUN adduser -D -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 3333

CMD ["flask", "run", "--host=0.0.0.0"]
