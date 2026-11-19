# Linux runner for the SWE-Bench-Fork harness (needs `resource`, POSIX paths).
# It talks to the host Docker daemon through the mounted socket.
FROM python:3.11.10-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir beautifulsoup4 chardet datasets docker ghapi GitPython python-dotenv requests rich unidiff tqdm
WORKDIR /work
