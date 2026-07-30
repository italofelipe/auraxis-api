ARG PYTHON_BASE_IMAGE=public.ecr.aws/docker/library/python:3.13.2-alpine
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

COPY requirements.txt .

# O tooling que vem na imagem base envelhece por conta própria e o Trivy acusa
# como HIGH sem que nada no requirements.txt mude: setuptools 70.3.0
# (CVE-2025-47273) e o msgpack vendorado pelo pip (GHSA-6v7p-g79w-8964).
# Nenhum dos dois é dependência da aplicação — atualizar aqui remove o achado na
# origem, em vez de silenciá-lo com exceção a cada nova advisory.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip setuptools && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 3333

CMD ["flask", "run", "--host=0.0.0.0"]
