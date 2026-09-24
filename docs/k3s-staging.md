# k3s staging deployment

This is a separate staging topology. It does not use `compose.yaml`,
`compose.production.yaml`, the homelab Docker network, the production
PostgreSQL volume, or the production database credentials.

## Topology and assumptions

- k3s provides the Kubernetes cluster, default local-path `StorageClass`, and
  Traefik ingress controller. This guide assumes the standard k3s install.
- PostgreSQL 16 runs as a single-replica StatefulSet in the
  `namicash-staging` namespace with a new 10 GiB PVC. It is reachable only by
  the backend through the in-cluster `postgresql` service.
- The backend uses the already-built backend image and runs its normal Alembic
  startup migration only against this new staging database.
- The frontend uses the already-built production Nginx image. Its existing
  `/api/` proxy resolves the Kubernetes `backend` Service, so no backend
  service is exposed through a load balancer.
- Traefik provides the public HTTPS entry point. Replace
  `staging.example.com` in `manifests/configmap.yaml`,
  `manifests/ingress.yaml`, and DNS with a hostname you control. The TLS
  certificate is supplied as the `namicash-staging-tls` Secret; certificate
  files must remain outside this repository.
- The images are expected in a registry reachable by the k3s nodes, or in the
  k3s container runtime. The manifests do not build or publish images.

The staging database is intentionally disposable/test-only. Do not restore a
production dump into it unless that is separately approved and sanitized.

## Prerequisites

Install `kubectl`, install/configure k3s on the target host(s), and configure
the kubeconfig context. On a k3s server, the kubeconfig is commonly available
at `/etc/rancher/k3s/k3s.yaml`; copy it securely to the operator machine and
set its server address appropriately.

```bash
export KUBECONFIG="$PWD/k3s.yaml"
kubectl config use-context default
kubectl get nodes
```

Build and push the existing Dockerfiles to a registry accessible by every k3s
node, or import the images into each node's containerd. For example:

```bash
docker build -t REGISTRY.example.com/namicash/backend:IMAGE_TAG ./backend
docker build --target production -t REGISTRY.example.com/namicash/frontend:IMAGE_TAG ./frontend
docker push REGISTRY.example.com/namicash/backend:IMAGE_TAG
docker push REGISTRY.example.com/namicash/frontend:IMAGE_TAG
```

Update the two `images` entries in
`deploy/k3s-staging/manifests/kustomization.yaml` to the exact registry paths
and immutable tag or digest to deploy. If the registry is private, create an
image-pull Secret in the staging namespace and reference it from the two
Deployments. Also replace the example hostname in the ConfigMap and Ingress,
then create its DNS A record pointing to the k3s Traefik host.

## Deploy

Create a local secrets file; it is ignored by the repository and must never be
committed:

```bash
cp deploy/k3s-staging/staging.env.example deploy/k3s-staging/staging.env
# Edit staging.env with new staging-only values.
chmod 600 deploy/k3s-staging/staging.env
deploy/k3s-staging/create-secrets.sh deploy/k3s-staging/staging.env
```

Create the TLS Secret from certificate material issued for the staging host.
Use cert-manager if it is installed, or create it manually without committing
the files:

```bash
kubectl -n namicash-staging create secret tls namicash-staging-tls \
  --cert=/secure/path/staging-fullchain.pem \
  --key=/secure/path/staging-privkey.pem
deploy/k3s-staging/deploy.sh deploy/k3s-staging/staging.env
```

The helpers create only staging Kubernetes resources. They do not read, alter,
migrate, or connect to the existing PostgreSQL database. Verify:

```bash
kubectl -n namicash-staging get pods,pvc,svc,ingress
curl --fail https://staging.example.com/health
```

Create the first staging administrator only after the app is healthy:

```bash
kubectl -n namicash-staging exec deploy/backend -- \
  python -m scripts.bootstrap_admin --email staging-admin@example.com \
  --display-name "Staging Administrator"
```

## Separation and cleanup

Local/homelab production remains managed only by
`docker compose --env-file .env.prod -f compose.production.yaml ...` and its
existing `cashbook-postgres-production-data` volume. Do not point the staging
`DATABASE_URL` at a host address, managed database instance, or any Compose
database.

To remove only staging application resources, delete the namespace. This also
deletes the staging PVC and its data; it has no effect on the homelab host:

```bash
kubectl delete namespace namicash-staging
```
