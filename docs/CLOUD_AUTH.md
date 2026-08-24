# Cloud Authentication

How bnkscope authenticates to EKS, GKE and AKS clusters.

---

## The short version

**bnkscope uses the credentials already on your machine.** It mounts
`~/.aws` and `~/.config/gcloud` **read-only** and mints cluster tokens itself,
in Python. There is no CLI in the image — no `aws`, no `gcloud`, no `kubectl`.

| Provider | How the token is obtained | Works? |
|---|---|---|
| **EKS** | boto3 SigV4-presigned STS → `k8s-aws-v1` token | Yes |
| **GKE** | google-auth, with ADC fallback | Yes |
| **AKS** | `kubelogin` — no Python equivalent | **No** |

So an `exec:` kubeconfig that shells out to `aws eks get-token`,
`aws-iam-authenticator` or `gke-gcloud-auth-plugin` works: bnkscope reads the
*intent* from the kubeconfig and does the equivalent natively, rather than
running the binary.

## AWS SSO

Log in on the host, as you normally would:

```bash
aws sso login --profile my-profile
```

bnkscope reads the refreshed cache out of `~/.aws` on its next probe. Set
`AWS_PROFILE` in the environment if you use a non-default profile — the compose
file passes it through only when it is set.

An expired SSO session shows up as a cluster that was reachable and now is not.
`aws sso login` again; nothing inside bnkscope needs restarting.

## AKS

There is no Python equivalent of `kubelogin`, and the image ships no CLI tools,
so an AKS context is **listed with that reason** rather than accepted and then
failing at connect time. Use a bearer token instead:

```bash
kubectl create token <serviceaccount> --duration=24h
```

and add the cluster by hand.

## Credential templates

The backend still exposes a credential-template API — including an AWS SSO
device-code flow, automatic refresh, and encrypted storage of the resulting
credentials — inherited from bnk-forge, where a deployment pipeline needed
credentials of its own.

> **There is currently no UI for it.** The `CredentialTemplates` and
> `ContainerRegistries` components exist in the frontend but are imported by no
> page, so the feature is reachable only over HTTP. For a local single-user
> tool the host-credentials path above is simpler and is the supported one.

If you want it back in the UI, the components are in
`frontend-v2/src/components/settings/`; the endpoints are under
`/api/credential-templates` and `/api/container-registries` in the
[API reference](API_REFERENCE.md).

## Storage

Whatever bnkscope does store — adopted kubeconfigs, and any credentials created
through the API — is encrypted at rest with a Fernet key (`ENCRYPTION_KEY`).
The key is included in a [backup](BACKUP_RESTORE_DESIGN.md), wrapped with a
passphrase you choose, because a database restored without it is a database full
of unreadable secrets.

Your own `~/.aws` and `~/.config/gcloud` are never written to.

---

| | |
|---|---|
| [User Guide](USER_GUIDE.md#first-run) | adding clusters |
| [Troubleshooting](TROUBLESHOOTING.md#a-cluster-is-missing-or-unreachable) | expired credentials, unsupported auth |
