# ============================================================================
# 1. PROVIDER & VARIABLES
# ============================================================================
terraform {
  required_version = ">= 1.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 5.0"
    }
  }
}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

variable "tenancy_ocid" {}
variable "user_ocid" {}
variable "fingerprint" {}
variable "private_key_path" {}
variable "region" {}
variable "compartment_ocid" {}
variable "project_name" { default = "healthcare" }
variable "freeform_tags" {
  type = map(string)
  default = {
    Project   = "Healthcare-IAM"
    ManagedBy = "Terraform"
  }
}

# ============================================================================
# 2. COMPARTMENTS
# ============================================================================
resource "oci_identity_compartment" "healthcare_root" {
  compartment_id = var.compartment_ocid
  description    = "Healthcare System - Root Compartment"
  name           = "${var.project_name}-root"
  enable_delete  = false
}

resource "oci_identity_compartment" "healthcare_security" {
  compartment_id = oci_identity_compartment.healthcare_root.id
  description    = "Security services - IAM, Audit, Cloud Guard"
  name           = "healthcare-security"
}

resource "oci_identity_compartment" "healthcare_shared_services" {
  compartment_id = oci_identity_compartment.healthcare_root.id
  description    = "Shared services - Vault, Logging, Monitoring"
  name           = "healthcare-shared-services"
}

resource "oci_identity_compartment" "clinical_dev" {
  compartment_id = oci_identity_compartment.healthcare_root.id
  description    = "Clinical systems development environment"
  name           = "clinical-dev"
}

resource "oci_identity_compartment" "clinical_test" {
  compartment_id = oci_identity_compartment.healthcare_root.id
  description    = "Clinical systems test environment"
  name           = "clinical-test"
}

resource "oci_identity_compartment" "clinical_prod" {
  compartment_id = oci_identity_compartment.healthcare_root.id
  description    = "Clinical systems production - PHI data boundary"
  name           = "clinical-prod"
}

# ============================================================================
# 3. GROUPS (Healthcare Roles)
# ============================================================================
resource "oci_identity_group" "security_admins" {
  compartment_id = var.tenancy_ocid
  description    = "Healthcare Security Administrators"
  name           = "HC-Security-Admins"
}

resource "oci_identity_group" "cloud_engineers" {
  compartment_id = var.tenancy_ocid
  description    = "Healthcare Cloud Engineers"
  name           = "HC-Cloud-Engineers"
}

resource "oci_identity_group" "clinical_app_admins" {
  compartment_id = var.tenancy_ocid
  description    = "Healthcare Clinical Application Administrators"
  name           = "HC-Clinical-App-Admins"
}

resource "oci_identity_group" "compliance_auditors" {
  compartment_id = var.tenancy_ocid
  description    = "Healthcare Compliance Auditors"
  name           = "HC-Compliance-Auditors"
}

resource "oci_identity_group" "clinical_developers" {
  compartment_id = var.tenancy_ocid
  description    = "Healthcare Clinical Developers"
  name           = "HC-Clinical-Developers"
}

resource "oci_identity_group" "data_analysts" {
  compartment_id = var.tenancy_ocid
  description    = "Healthcare Data Analysts"
  name           = "HC-Data-Analysts"
}

# ============================================================================
# 4. POLICIES (Security Rules) - 
# ============================================================================
resource "oci_identity_policy" "security_admins_policy" {
  # CHANGED: Now attached to the Healthcare Root instead of the Tenancy
  compartment_id = oci_identity_compartment.healthcare_root.id 
  description    = "Policy for Healthcare Security Administrators"
  name           = "HC-Security-Admins-Policy"
  
  statements     = [
    "Allow group HC-Security-Admins to manage all-resources in compartment healthcare-security",
    "Allow group HC-Security-Admins to manage vaults in compartment healthcare-shared-services"
  ]
}

resource "oci_identity_policy" "clinical_developers_policy" {
  # CHANGED: Now attached to the Healthcare Root instead of the Tenancy
  compartment_id = oci_identity_compartment.healthcare_root.id
  description    = "Policy for Healthcare Clinical Developers"
  name           = "HC-Clinical-Developers-Policy"
  
  statements     = [
    "Allow group HC-Clinical-Developers to manage all-resources in compartment clinical-dev",
    "Allow group HC-Clinical-Developers to read all-resources in compartment clinical-test"
  ]
}

# Note: These two statements must stay at the Tenancy level to work
resource "oci_identity_policy" "tenancy_level_security_policy" {
  compartment_id = var.tenancy_ocid
  description    = "Global security permissions"
  name           = "HC-Tenancy-Security-Policy"
  statements     = [
    "Allow group HC-Security-Admins to manage cloud-guard-family in tenancy",
    "Allow group HC-Security-Admins to read audit-events in tenancy"
  ]
}

# ============================================================================
# 5. VAULT (Secret Management)
# ============================================================================
resource "oci_kms_vault" "healthcare_vault" {
  compartment_id = oci_identity_compartment.healthcare_shared_services.id
  display_name   = "Healthcare-Secrets-Vault"
  vault_type     = "DEFAULT"
}

resource "oci_kms_key" "clinical_app_master_key" {
  compartment_id      = oci_identity_compartment.healthcare_shared_services.id
  display_name        = "clinical-app-master-key"
  management_endpoint = oci_kms_vault.healthcare_vault.management_endpoint
  key_shape {
    algorithm = "AES"
    length    = 32
  }
}

# ============================================================================
# 6. DYNAMIC GROUP
# ============================================================================

resource "oci_identity_dynamic_group" "clinical_app_instances" {
    # Dynamic groups must be created in the Tenancy (root)
    compartment_id = var.tenancy_ocid
    description    = "Automatic group for all servers in the clinical-dev compartment"
    
    # This logic tells OCI: "Any server born in clinical-dev is automatically a member"
    matching_rule  = "ALL {instance.compartment.id = '${oci_identity_compartment.clinical_dev.id}'}"
    name           = "HC-Clinical-App-Instances"
}

# This policy gives the SERVERS (the Dynamic Group) permission to use the Vault
resource "oci_identity_policy" "dynamic_group_policy" {
    compartment_id = oci_identity_compartment.healthcare_root.id
    description    = "Allows dev servers to use encryption keys"
    name           = "HC-Instance-Encryption-Policy"

    statements = [
        "Allow dynamic-group HC-Clinical-App-Instances to use keys in compartment healthcare-shared-services"
    ]
}

# ============================================================================
# 7. MULTI-CLOUD FEDERATION (AWS to OCI)
# ============================================================================

# This resource creates the "Trust" relationship in OCI
resource "oci_identity_identity_provider" "aws_idp" {
  compartment_id = var.tenancy_ocid
  description    = "Federation from AWS IAM Identity Center"
  name           = "AWS-Federation"
  product_type   = "SAML2"
  protocol       = "SAML2"

  # You will get this XML metadata from the AWS Console in the next step
  # For now, we use a placeholder or a local file path
  metadata_url = "https://portal.sso.us-east-1.amazonaws.com/saml/metadata/placeholder"
  
  freeform_tags = {
    "Partner" = "AWS"
    "Project" = "Multi-Cloud-IAM"
  }
}

# Group Mapping: Connect an AWS Group to your OCI 'HC-Security-Admins'
resource "oci_identity_idp_group_mapping" "aws_to_oci_admin_mapping" {
  idp_id            = oci_identity_identity_provider.aws_idp.id
  idp_group_name    = "AWS-Security-Admins" # The name of the group in AWS
  group_id          = oci_identity_group.security_admins.id
}