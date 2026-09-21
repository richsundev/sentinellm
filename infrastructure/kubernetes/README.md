# Kubernetes manifests

Plain manifests (no Helm/Kustomize layering) for running SentinelLLM on a
Kubernetes cluster. They demonstrate the shape of a real deployment —
separate API/worker/frontend Deployments, HPAs, a migration Job run before
rollout, config/secret separation — but **this is not a production-ready
manifest set as-is**. Treat it as a starting point.

## Apply order

```bash
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
cp secret.yaml.example secret.yaml   # fill in real values first
kubectl apply -f secret.yaml
kubectl apply -f postgres.yaml -f redis.yaml
kubectl wait --for=condition=ready pod -l app=postgres -n sentinellm --timeout=120s
kubectl apply -f migrate-job.yaml
kubectl wait --for=condition=complete job/sentinel-migrate -n sentinellm --timeout=120s
kubectl apply -f api-deployment.yaml -f worker-deployment.yaml -f frontend-deployment.yaml
kubectl apply -f ingress.yaml   # optional, requires nginx-ingress + cert-manager
```

## What this does NOT give you

Being explicit about this, per the project's engineering-quality bar:

- **Stateful services are single-replica, in-cluster, unmanaged.** `postgres.yaml`
  and `redis.yaml` are convenience manifests for a demo/dev cluster — no
  automated backups, no failover, no PITR. A real deployment needs a managed
  database (RDS/Cloud SQL/Aurora) and managed Redis (ElastiCache/Memorystore),
  or a proper operator (CloudNativePG, redis-operator) with PodDisruptionBudgets.
- **No secret manager integration.** `secret.yaml.example` is a plain
  Kubernetes `Secret` template (base64, not encrypted at rest by default).
  Production should use Vault, External Secrets Operator, or your cloud
  provider's KMS-backed secret store, not hand-applied plaintext.
- **No NetworkPolicies.** Every pod can currently reach every other pod in
  the namespace; a real deployment should restrict traffic (e.g. only `api`
  and `worker` may reach `postgres`/`redis`).
- **No PodDisruptionBudgets or topology spread constraints**, so a node
  drain can take out all replicas of a Deployment simultaneously.
- **Images are referenced as `ghcr.io/OWNER/sentinellm-*:latest`** —
  placeholders. A real pipeline should build immutable, digest-pinned tags
  (see `.github/workflows/build.yml`) and never deploy `:latest`.
- **The worker HPA scales on CPU only.** The workload is I/O- and
  queue-bound, not CPU-bound; scaling on the queue would react far more
  quickly to a burst of ingested traces. The worker already exports
  `sentinel_queue_depth` (`:9100/metrics`, scraped via the pod annotations in
  `worker-deployment.yaml`); what's missing is a prometheus-adapter rule
  exposing it as a custom metric and an HPA `Pods`/`External` metric block
  using it — see `docs/performance.md`.
- **No Prometheus/Grafana in the manifests.** The worker and API expose
  metrics and the pod annotations are in place, but running Prometheus is
  left to your cluster (kube-prometheus-stack works with the annotations or
  a `PodMonitor`). The dashboard and alert rules to load are in
  `infrastructure/monitoring/`.
- **No TLS between in-cluster services** (only at the ingress edge via
  cert-manager). Fine for a single-tenant namespace; not fine for a
  multi-tenant cluster.
- **No resource quotas / LimitRanges at the namespace level.**

## What it does demonstrate correctly

- Safe horizontal scaling of the worker: its evaluation consumer is
  idempotent, and its periodic passes (regression, alerting, model health,
  canary rollouts) are serialised across replicas by Postgres advisory locks,
  so `replicas: 2` and an HPA up to 10 don't double-apply a rollout step or
  double-fire an alert.

- Config/secret separation (`ConfigMap` for non-sensitive values, `Secret`
  for credentials), consumed via `envFrom` — never baked into the image.
- A migration `Job` run to completion before the API/worker rollout, so a
  new pod never starts against a schema it doesn't understand.
- Readiness (`/ready`, which checks the database) and liveness (`/health`,
  which deliberately doesn't — restarting the API doesn't fix a database
  outage) probes on the API, and a real page for the frontend, not just "the
  process is running."
- Horizontal Pod Autoscalers on both the API and worker tiers with
  independent min/max bounds, reflecting that they scale for different
  reasons (request concurrency vs. evaluation throughput).
