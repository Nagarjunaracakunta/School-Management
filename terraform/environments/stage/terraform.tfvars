# STAGE values. Committed on purpose: they are not secrets. Anything secret never goes in a .tfvars file.
# Like prod in shape, cheaper in size. Pulls images from the dev account's registry.
#
# The account ids below are PLACEHOLDERS. Replace them with your real 12-digit AWS account ids before running plan.

environment         = "stage"
allowed_account_ids = ["222222222222"]
owner               = "platform-team"

vpc_cidr            = "10.20.0.0/16"
az_count            = 2
nat_mode            = "single"
enable_flow_logs    = true
interface_endpoints = []

manage_ecr           = false
ecr_owner_account_id = "111111111111" # the account that owns the registry (dev). A PLACEHOLDER: use the real id.
ecr_pull_account_ids = []

# ---- database ---------------------------------------------------------------------------------------------------------------
rds_instance_class           = "db.t4g.small"
rds_allocated_storage_gb     = 20
rds_max_allocated_storage_gb = 100
rds_multi_az                 = false
rds_backup_retention_days    = 7
rds_deletion_protection      = false
rds_skip_final_snapshot      = false
rds_performance_insights     = false
secrets_recovery_days        = 7

# ---- messaging and frontend --------------------------------------------------------------------------------------------------
alert_emails           = [] # put real addresses here; each person must click the confirmation link AWS emails
ses_from_address       = "" # a verified sender, for example "no-reply@school.example"; empty disables email delivery
frontend_force_destroy = true

# ---- Kubernetes (EKS) ---------------------------------------------------------------------------------------------------
# Check `aws eks describe-addon-versions` and use the newest version with STANDARD support (older ones cost extra).
kubernetes_version = "1.34"

# Who may reach the Kubernetes API from the internet. 203.0.113.0/24 is a documentation range (a PLACEHOLDER): replace it
# with your own address, for example ["198.51.100.20/32"]. 0.0.0.0/0 is refused. Use [] to allow only access from inside the VPC.
eks_public_access_cidrs = ["203.0.113.7/32"]

# Who is cluster admin. A PLACEHOLDER role ARN: replace with your real administrators' role (an IAM role, ideally one that
# people assume through SSO), not a personal access key.
eks_admin_principal_arns = ["arn:aws:iam::222222222222:role/PlatformAdmins"]

node_instance_types = ["t3.medium"]
node_min_size       = 2
node_desired_size   = 2
node_max_size       = 4


# ---- CI pipeline ----------------------------------------------------------------------------------------------------------
# Not used here: this environment does not own the registry (manage_ecr = false), so no push role is created.
github_repository = "OWNER/school-management"
