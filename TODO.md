# TODO - Security & Improvements

## 🔴 Critical (Before Production)

- [ ] **Flower Authentication**: Add nginx basic auth (`auth_basic`) or IP allowlist for `/flower/` endpoint. Currently exposed without auth.
- [ ] **HTTPS/TLS**: Replace HTTP with HTTPS. Use Let's Encrypt (staging) or self-signed certs for now. nginx needs SSL configuration.
- [ ] **Secrets Management**: Move from `.env` file to Docker secrets or external vault (HashiCorp Vault, AWS Secrets Manager). `.env` should not be used in production.
- [ ] **API Authentication**: OpenCLAW → API communication needs auth token/API key validation. Currently no auth on endpoints.

## 🟡 High Priority (Before Staging)

- [ ] **Rate Limit Tuning**: Current: 10 req/sec burst 20. Monitor and adjust based on OpenCLAW usage patterns.
- [ ] **Resource Limits**: Worker memory capped at 4GB — verify BGE-M3 + batch processing doesn't exceed this.
- [ ] **Health Check Endpoints**: API needs `/health` and `/ready` endpoints (readiness vs liveness distinction).
- [ ] **PostgreSQL**: Add when document metadata storage outgrows Redis. Include `pg_isready` healthcheck.

## 🟢 Medium Priority (Post-MVP)

- [ ] **Structured Logging**: JSON format for log aggregation (ELK, Datadog, Loki). Currently plain text.
- [ ] **Monitoring/Alerting**: Prometheus metrics endpoint + Grafana dashboard. Flower is not enough for production monitoring.
- [ ] **Backup Strategy**: Qdrant snapshots, Obsidian vault git backup, Redis persistence configuration.
- [ ] **Graceful Shutdown**: Verify Celery `STOPSIGNAL SIGTERM` handles in-flight tasks correctly.

## 💡 Nice to Have

- [ ] **Auto-scaling**: Horizontal pod autoscaling for workers based on queue depth.
- [ ] **Circuit Breaker**: If Qdrant/Redis down, fail fast instead of hanging.
- [ ] **Request ID Tracing**: Pass correlation ID through API → Celery → workers for debugging.
- [ ] **Input Sanitization**: Deep content validation on uploaded documents (malware scan, size check beyond nginx layer).
