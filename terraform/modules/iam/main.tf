# EKS Pod Identity: a pod gets the permissions of ONE role, picked by an "association" (cluster, namespace, service
# account) that the EKS module creates in Phase 14. The trust policy below lets the EKS service hand out the role's
# credentials to pods. Unlike the older IRSA, it does not mention a specific cluster, so these roles can exist (and be
# reviewed) before the cluster does.
#
# Policies are written with jsonencode (not aws_iam_policy_document) so the tests can read exactly what each role may do.
locals {
  trust_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
}

resource "aws_iam_role" "this" {
  for_each = var.roles

  name               = "${var.name_prefix}-${each.key}"
  description        = each.value.description
  assume_role_policy = local.trust_policy

  tags = merge(var.tags, { Service = each.key })
}

resource "aws_iam_role_policy" "this" {
  for_each = var.roles

  name = "permissions"
  role = aws_iam_role.this[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [for st in each.value.statements : {
      Sid      = st.sid
      Effect   = "Allow"
      Action   = st.actions
      Resource = st.resources
    }]
  })
}
