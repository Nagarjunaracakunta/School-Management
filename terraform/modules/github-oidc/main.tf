# GitHub Actions proves who it is to AWS with a short-lived OpenID Connect (OIDC) token that GitHub signs for each job. AWS
# checks the signature against GitHub's public keys and the token's "subject" against this role's trust policy. No access key
# is stored in GitHub, so there is nothing to leak or rotate.
locals {
  issuer = "token.actions.githubusercontent.com"
  # Exactly the jobs that run in the named GitHub Environment of exactly this repository.
  subject = "repo:${var.github_repository}:environment:${var.github_environment}"
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_provider ? 1 : 0

  url            = "https://${local.issuer}"
  client_id_list = ["sts.amazonaws.com"]
  # AWS validates GitHub's certificate chain itself; no thumbprint needs to be maintained.
  tags = var.tags
}

data "aws_caller_identity" "current" {}

locals {
  provider_arn = var.create_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${local.issuer}"
}

locals {
  push_enabled     = length(var.ecr_repository_arns) > 0
  frontend_enabled = var.create_frontend_deploy_role
  frontend_subject = "repo:${var.github_repository}:environment:${var.frontend_github_environment}"
}

resource "aws_iam_role" "ecr_push" {
  count = local.push_enabled ? 1 : 0

  name        = "${var.name_prefix}-github-ecr-push"
  description = "Assumed by GitHub Actions (${var.github_repository}, environment ${var.github_environment}) to push container images"
  # Sessions end after one hour; a build never needs longer.
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.issuer}:aud" = "sts.amazonaws.com"
          "${local.issuer}:sub" = local.subject
        }
      }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "ecr_push" {
  count = local.push_enabled ? 1 : 0

  name = "push-images"
  role = aws_iam_role.ecr_push[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # The login token request cannot be limited to a repository: AWS only allows "*" here.
        Sid      = "GetRegistryLoginToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "PushAndInspectOurRepositoriesOnly"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          "ecr:BatchGetImage",
          "ecr:DescribeImages",
        ]
        Resource = var.ecr_repository_arns
      },
    ]
  })
}

# ---- deploying the website: copy files into ONE bucket, then tell CloudFront to forget its old copies -------------------
resource "aws_iam_role" "frontend_deploy" {
  count = local.frontend_enabled ? 1 : 0

  name                 = "${var.name_prefix}-github-frontend-deploy"
  description          = "Assumed by GitHub Actions (${var.github_repository}, environment ${var.frontend_github_environment}) to publish the website"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.issuer}:aud" = "sts.amazonaws.com"
          "${local.issuer}:sub" = local.frontend_subject
        }
      }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "frontend_deploy" {
  count = local.frontend_enabled ? 1 : 0

  name = "publish-website"
  role = aws_iam_role.frontend_deploy[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListTheBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = var.frontend_bucket_arn
      },
      {
        Sid      = "ReplaceFilesInTheBucket"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = "${var.frontend_bucket_arn}/*"
      },
      {
        Sid      = "InvalidateTheCache"
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation"]
        Resource = var.frontend_distribution_arn
      },
    ]
  })
}
