# DEV values. Committed on purpose: they are not secrets. Anything secret never goes in a .tfvars file.
# Cheapest settings: one shared NAT gateway, no flow logs, no private endpoints.
# dev OWNS the container registry: images are built once, here, and stage/prod pull them.
#
# The account ids below are PLACEHOLDERS. Replace them with your real 12-digit AWS account ids before running plan.

environment         = "dev"
allowed_account_ids = ["111111111111"]
owner               = "platform-team"

vpc_cidr            = "10.10.0.0/16"
az_count            = 2
nat_mode            = "single"
enable_flow_logs    = false
interface_endpoints = []

manage_ecr           = true
ecr_pull_account_ids = ["222222222222", "333333333333"]

# ---- database ---------------------------------------------------------------------------------------------------------------
rds_instance_class           = "db.t4g.micro"
rds_allocated_storage_gb     = 20
rds_max_allocated_storage_gb = 50
rds_multi_az                 = false
rds_backup_retention_days    = 1
rds_deletion_protection      = false
rds_skip_final_snapshot      = true
rds_performance_insights     = false
secrets_recovery_days        = 0

# ---- messaging and frontend --------------------------------------------------------------------------------------------------
alert_emails           = [] # put real addresses here; each person must click the confirmation link AWS emails
ses_from_address       = "" # a verified sender, for example "no-reply@school.example"; empty disables email delivery
frontend_force_destroy = true

# No domain name yet? Keep "http": CloudFront reaches the load balancer over plain HTTP (dev only; the guardrails refuse it in
# stage and prod). With your own domain and an ACM certificate, switch to "https", set the certificate on the load balancer
# (render-env-values.py --certificate-arn ...) and api_origin_domain_name to the name on that certificate.
api_origin_protocol = "http"

# ---- Kubernetes (EKS) ---------------------------------------------------------------------------------------------------
# Check `aws eks describe-addon-versions` and use the newest version with STANDARD support (older ones cost extra).
kubernetes_version = "1.34"

# Who may reach the Kubernetes API from the internet. 203.0.113.0/24 is a documentation range (a PLACEHOLDER): replace it
# with your own address, for example ["198.51.100.20/32"]. 0.0.0.0/0 is refused. Use [] to allow only access from inside the VPC.
eks_public_access_cidrs = ["203.0.113.7/32"]

# Who is cluster admin. A PLACEHOLDER role ARN: replace with your real administrators' role (an IAM role, ideally one that
# people assume through SSO), not a personal access key.
eks_admin_principal_arns = ["arn:aws:iam::111111111111:role/PlatformAdmins"]

node_instance_types = ["t3.medium"]
node_min_size       = 1
node_desired_size   = 2
node_max_size       = 3


# ---- CI pipeline ------------------------------------------------------------------------------------------------------------
github_repository = "OWNER/school-management" # a PLACEHOLDER: your GitHub organisation or user, and the repository name
