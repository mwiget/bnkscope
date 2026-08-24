"""System models: ApplicationSetting, SyncJob, CloudCredentialTemplate, Notification, HelmChart."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class ApplicationSetting(Base):
    """Application configuration and settings."""
    __tablename__ = "application_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, nullable=False, index=True)
    value = Column(Text)
    value_type = Column(String(50), default="string")
    description = Column(Text)
    category = Column(String(100), default="general", index=True)
    is_encrypted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class CloudCredentialTemplate(Base):
    """Reusable cloud provider credential templates."""
    __tablename__ = "cloud_credential_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text)
    provider = Column(String(50), nullable=False)

    # AWS credentials
    aws_auth_method = Column(String(50))
    aws_profile = Column(String(100))
    region = Column(String(50))
    aws_access_key_id = Column(String(100))
    aws_secret_access_key_encrypted = Column(Text)
    aws_session_token_encrypted = Column(Text)
    aws_credentials_expiry = Column(DateTime(timezone=True))

    # AWS SSO
    aws_sso_enabled = Column(Boolean, default=False)
    aws_sso_start_url = Column(String(500))
    aws_sso_region = Column(String(50))
    aws_sso_account_id = Column(String(20))
    aws_sso_role_name = Column(String(255))

    # AWS SSO Session
    aws_sso_access_token_encrypted = Column(Text)
    aws_sso_refresh_token_encrypted = Column(Text)
    aws_sso_client_id = Column(String(255))
    aws_sso_client_secret_encrypted = Column(Text)
    aws_sso_token_expiry = Column(DateTime(timezone=True))
    aws_sso_authenticated_at = Column(DateTime(timezone=True))

    # GCP credentials (future)
    gcp_credentials_encrypted = Column(Text)
    gcp_project_id = Column(String(255))

    # Azure credentials (future)
    azure_subscription_id = Column(String(255))
    azure_tenant_id = Column(String(255))
    azure_credentials_encrypted = Column(Text)

    # IBM Cloud credentials
    ibmcloud_api_key_encrypted = Column(Text)
    ibmcloud_resource_group = Column(String(255))
    ibm_cos_instance_name = Column(String(255))
    ibm_cos_instance_crn = Column(Text)
    ibm_cos_hmac_access_key_id = Column(String(255))
    ibm_cos_hmac_secret_access_key_encrypted = Column(Text)
    # Cached IAM bearer token (short-lived; refreshed on demand). Mirrors
    # AWS aws_credentials_expiry / aws_sso_token_expiry. Saves a ~250ms
    # /identity/token round-trip on every IBM region listing, COS query,
    # and engine_router kubeconfig refresh.
    ibm_iam_token_encrypted = Column(Text, nullable=True)
    ibm_iam_token_expiry = Column(DateTime(timezone=True), nullable=True)

    # Terraform Cloud (private modules). Bearer token encrypted with the same
    # Fernet key as other secrets; hostname defaults to app.terraform.io and
    # supports Terraform Enterprise self-hosted instances.
    tfc_api_token_encrypted = Column(Text, nullable=True)
    tfc_hostname = Column(String(255), nullable=True)

    # SSH / On-Premises credentials
    ssh_host = Column(String(255), nullable=True)
    ssh_port = Column(Integer, default=22, nullable=True)
    ssh_username = Column(String(255), nullable=True)
    ssh_auth_type = Column(String(50), nullable=True)
    ssh_password_encrypted = Column(Text, nullable=True)
    ssh_key_encrypted = Column(Text, nullable=True)
    ssh_key_passphrase_encrypted = Column(Text, nullable=True)

    # Generic credentials field
    credentials_encrypted = Column(Text)

    # Passive cloud-API observation (RFC connectivity Phase 2). Every
    # successful boto3 call stamps last_successful_call_at; every failure
    # stamps last_error_*. UI reads these for an at-a-glance "credential
    # health" indicator without forcing a synchronous test.
    last_successful_call_at = Column(DateTime(timezone=True), nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(64), nullable=True)
    last_error_message = Column(Text, nullable=True)

    # Metadata
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String(255))

    # Relationship
    clusters = relationship(
        "KubernetesCluster",
        back_populates="credential_template",
        foreign_keys="KubernetesCluster.credential_template_id",
    )

class Notification(Base):
    """User notifications for deployment events and system alerts."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user = Column(String(255), index=True)
    type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    resource_type = Column(String(100))
    resource_id = Column(Integer)
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at = Column(DateTime(timezone=True))

    # D-025 P1: extended notification fields
    severity = Column(String(20), nullable=False, server_default="info")
    category = Column(String(50), nullable=False, server_default="general", index=True)
    action_url = Column(String(512), nullable=True)
    dedupe_key = Column(String(255), nullable=True, index=True)
    # "metadata" is a reserved name on SQLAlchemy Declarative; use attribute name
    # extra_metadata mapped to column name "metadata"
    extra_metadata = Column("metadata", JSON, nullable=True)

    __table_args__ = (
        Index("idx_notification_user_unread", "user", "is_read"),
        Index("idx_notification_user_dedupe", "user", "dedupe_key"),
    )

