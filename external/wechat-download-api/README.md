# wechat-download-api External Service

This directory manages the self-hosted `wechat-download-api` service as an external dependency.

The third-party source code is not vendored into `langgraph-study`. The workflow talks to the service through HTTP, usually `http://localhost:5000`.

## Start

```bash
cp .env.example .env
docker compose up -d
```

Open `http://localhost:5000/login.html` and scan the QR code with a WeChat Official Account admin account.

## Check

```bash
curl http://localhost:5000/api/health
```

## Stop

```bash
docker compose down
```
