/**
 * Cloud and SSH credential types.
 *
 * These lived in types/projects.ts until projects were removed (bnkscope
 * Phase 2). They describe credentials attached to a cluster, not to a project.
 */




export interface CloudCredentialTemplate {
  id: number;
  name: string;
  description?: string;
  provider: string; // aws, gcp, azure, ibm, ssh
  aws_auth_method?: string; // profile, access_keys, sso
  aws_profile?: string;
  region?: string;
  aws_access_key_id?: string;
  has_aws_secret_access_key: boolean;
  has_aws_session_token: boolean;
  aws_sso_enabled: boolean;
  aws_sso_start_url?: string;
  aws_sso_region?: string;
  aws_sso_account_id?: string;
  aws_sso_role_name?: string;
  aws_sso_authenticated_at?: string;
  aws_sso_token_expiry?: string;
  aws_credentials_expiry?: string;
  gcp_project_id?: string;
  has_gcp_credentials: boolean;
  azure_subscription_id?: string;
  azure_tenant_id?: string;
  has_azure_credentials: boolean;
  has_ibmcloud_api_key: boolean;
  ibmcloud_resource_group?: string;
  ibm_cos_instance_name?: string;
  has_tfc_api_token?: boolean;
  tfc_hostname?: string;
  // SSH / On-Premises
  ssh_host?: string;
  ssh_port?: number;
  ssh_username?: string;
  ssh_auth_type?: string; // 'key' or 'password'
  has_ssh_password: boolean;
  has_ssh_key: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
  projects_count: number;
  // Passive cloud-API observation (RFC connectivity Phase 2). Populated by
  // every real boto3 call site so the UI can show "AWS access OK as of X"
  // without re-clicking Test.
  last_successful_call_at?: string | null;
  last_error_at?: string | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
}




