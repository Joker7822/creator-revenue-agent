from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra" / "gcp" / "production"
MAIN = (INFRA / "main.tf").read_text(encoding="utf-8")
VARIABLES = (INFRA / "variables.tf").read_text(encoding="utf-8")
VERSIONS = (INFRA / "versions.tf").read_text(encoding="utf-8")
RBAC = (
    ROOT
    / "deploy"
    / "kubernetes"
    / "production-deployer-gcp-rbac.example.yaml"
).read_text(encoding="utf-8")
PREFLIGHT = (
    ROOT / ".github" / "workflows" / "production-preflight.yml"
).read_text(encoding="utf-8")
DEPLOY = (
    ROOT / ".github" / "workflows" / "production-deploy.yml"
).read_text(encoding="utf-8")
INFRA_WORKFLOW = (
    ROOT / ".github" / "workflows" / "gcp-production-infra.yml"
).read_text(encoding="utf-8")


def test_gke_is_regional_autopilot_private_and_dns_only() -> None:
    assert 'enable_autopilot = true' in MAIN
    assert 'enable_private_nodes = true' in MAIN
    assert 'control_plane_endpoints_config {' in MAIN
    assert 'allow_external_traffic    = true' in MAIN
    assert 'enable_k8s_tokens_via_dns = false' in MAIN
    assert 'enable_k8s_certs_via_dns  = false' in MAIN
    assert 'ip_endpoints_config {' in MAIN
    assert 'enabled = false' in MAIN
    assert 'deletion_protection = true' in MAIN


def test_cloud_sql_is_private_ha_backed_up_and_destroy_protected() -> None:
    assert 'database_version = "POSTGRES_17"' in MAIN
    assert 'availability_type = "REGIONAL"' in MAIN
    assert 'ipv4_enabled    = false' in MAIN
    assert 'point_in_time_recovery_enabled = true' in MAIN
    assert 'backup_retention_settings {' in MAIN
    assert 'deletion_protection_enabled = true' in MAIN
    assert 'prevent_destroy = true' in MAIN


def test_audit_anchor_storage_is_separate_and_worm_oriented() -> None:
    assert 'var.audit_anchor_project_id != var.project_id' in VARIABLES
    assert 'provider = google.anchor' in MAIN
    assert 'public_access_prevention    = "enforced"' in MAIN
    assert 'uniform_bucket_level_access = true' in MAIN
    assert 'force_destroy               = false' in MAIN
    assert 'retention_policy {' in MAIN
    assert 'is_locked        = var.lock_audit_anchor_bucket' in MAIN
    assert 'role   = "roles/storage.objectCreator"' in MAIN
    assert 'role   = "roles/storage.objectViewer"' in MAIN
    assert 'roles/storage.objectAdmin' not in MAIN


def test_github_federation_is_immutable_repo_and_environment_scoped() -> None:
    assert 'issuer_uri = "https://token.actions.githubusercontent.com/"' in MAIN
    assert 'attribute.repository_id' in MAIN
    assert 'attribute.repository_owner_id' in MAIN
    assert "assertion.repository_id == '${var.github_repository_id}'" in MAIN
    assert (
        "assertion.repository_owner_id == "
        "'${var.github_repository_owner_id}'"
        in MAIN
    )
    assert "assertion.ref == 'refs/heads/main'" in MAIN
    assert "assertion.sub.endsWith(':environment:production')" in MAIN
    assert '/attribute.repository_id/${var.github_repository_id}' in MAIN
    assert '"container.clusters.connect"' in MAIN
    assert '"container.clusters.get"' in MAIN


def test_terraform_does_not_store_application_secret_versions() -> None:
    assert 'google_secret_manager_secret_version' not in MAIN
    assert 'google_sql_user' not in MAIN


def test_production_iac_versions_are_exactly_pinned() -> None:
    assert 'required_version = "= 1.16.4"' in VERSIONS
    assert 'version = "= 8.5.0"' in VERSIONS
    assert 'terraform_version: "1.16.4"' in INFRA_WORKFLOW


def test_gcp_deployer_rbac_preserves_secret_and_namespace_boundaries() -> None:
    assert 'kind: User' in RBAC
    assert 'creator-revenue-agent-secrets' in RBAC
    assert 'ghcr-pull' in RBAC
    secret_rule = RBAC.split('resources:\n      - secrets', 1)[1].split(
        '  - apiGroups:', 1
    )[0]
    assert '      - get' in secret_rule
    assert '      - create' not in secret_rule
    assert '      - patch' not in secret_rule
    namespace_rule = RBAC.split('resources:\n      - namespaces', 1)[1]
    assert '      - get' in namespace_rule
    assert '      - delete' not in namespace_rule


def test_production_workflows_use_oidc_and_dns_gke_credentials() -> None:
    for text in (PREFLIGHT, DEPLOY):
        assert 'id-token: write' in text
        assert 'GCP_WIF_PROVIDER' in text
        assert 'GCP_DEPLOY_SERVICE_ACCOUNT' in text
        assert 'google-github-actions/auth@' in text
        assert 'google-github-actions/get-gke-credentials@' in text
        assert 'use_dns_based_endpoint: true' in text
        assert 'context_name: production' in text
        assert 'KUBECONFIG_B64' not in text


def test_terraform_validation_workflow_uses_pinned_action() -> None:
    assert 'terraform fmt -check -recursive infra/gcp/production' in INFRA_WORKFLOW
    assert 'terraform -chdir=infra/gcp/production init -backend=false' in INFRA_WORKFLOW
    assert 'terraform -chdir=infra/gcp/production validate' in INFRA_WORKFLOW
    assert (
        'hashicorp/setup-terraform@'
        'dfe3c3f87815947d99a8997f908cb6525fc44e9e'
        in INFRA_WORKFLOW
    )
