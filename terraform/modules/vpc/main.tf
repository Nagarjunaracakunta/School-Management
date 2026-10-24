data "aws_region" "current" {}

locals {
  # ---- address plan ---------------------------------------------------------------------------------------------
  # For a /16 such as 10.10.0.0/16 (index = position of the zone in var.azs):
  #   public    /24  10.10.<index>.0              load balancers and NAT gateways only; nothing else lives here
  #   private   /20  10.10.<16 * (index+1)>.0     the Kubernetes nodes and pods (big: every pod gets its own IP)
  #   database  /24  10.10.<200 + index>.0        RDS; no route to the internet at all
  az_index       = { for i, az in var.azs : az => i }
  public_cidrs   = { for az, i in local.az_index : az => cidrsubnet(var.cidr_block, 8, i) }
  private_cidrs  = { for az, i in local.az_index : az => cidrsubnet(var.cidr_block, 4, i + 1) }
  database_cidrs = { for az, i in local.az_index : az => cidrsubnet(var.cidr_block, 8, 200 + i) }

  # ---- NAT gateways ---------------------------------------------------------------------------------------------
  # Which zones get a NAT gateway. A conditional that picks a list, then for_each over it: adding or removing a
  # zone adds or removes exactly that zone's NAT, and never disturbs the others.
  nat_azs = (
    var.nat_mode == "per_az" ? var.azs :
    var.nat_mode == "single" ? slice(var.azs, 0, 1) :
    []
  )
  # Each private subnet sends internet traffic to the NAT in its own zone, or to the single shared one.
  nat_for_az = {
    for az in var.azs : az => var.nat_mode == "per_az" ? az : try(local.nat_azs[0], null)
  }

  cluster_tag = var.eks_cluster_name == "" ? {} : { "kubernetes.io/cluster/${var.eks_cluster_name}" = "shared" }
}

# ---------------------------------------------------------------------------------------------------------------
# The network itself
# ---------------------------------------------------------------------------------------------------------------
resource "aws_vpc" "this" {
  cidr_block           = var.cidr_block
  enable_dns_support   = true # needed so pods and nodes can resolve names (including the AWS service endpoints)
  enable_dns_hostnames = true

  tags = merge(var.tags, { Name = var.name })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name}-igw" })
}

# The VPC's built-in "default" security group allows all traffic between its members. Anything that forgets to
# choose a security group lands in it. Emptying it makes forgetting harmless: no rules means no traffic.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name}-default-deny" })
}

# ---------------------------------------------------------------------------------------------------------------
# Subnets: one per zone per tier. for_each (not count) keys them by zone name, so removing a zone from the middle
# of the list never renumbers and recreates the others.
# ---------------------------------------------------------------------------------------------------------------
resource "aws_subnet" "public" {
  for_each = local.public_cidrs

  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = each.value
  map_public_ip_on_launch = false # nothing here should get a public address by accident; load balancers ask for theirs

  tags = merge(var.tags, local.cluster_tag, {
    Name                     = "${var.name}-public-${each.key}"
    Tier                     = "public"
    "kubernetes.io/role/elb" = "1" # internet-facing load balancers are placed in subnets with this tag
  })
}

resource "aws_subnet" "private" {
  for_each = local.private_cidrs

  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value

  tags = merge(var.tags, local.cluster_tag, {
    Name                              = "${var.name}-private-${each.key}"
    Tier                              = "private"
    "kubernetes.io/role/internal-elb" = "1" # internal load balancers
  })
}

resource "aws_subnet" "database" {
  for_each = local.database_cidrs

  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value

  tags = merge(var.tags, { Name = "${var.name}-database-${each.key}", Tier = "database" })
}

# ---------------------------------------------------------------------------------------------------------------
# Outbound internet for the private subnets: NAT gateways (see var.nat_mode)
# ---------------------------------------------------------------------------------------------------------------
resource "aws_eip" "nat" {
  for_each = toset(local.nat_azs)

  domain = "vpc"

  tags = merge(var.tags, { Name = "${var.name}-nat-${each.key}" })
}

resource "aws_nat_gateway" "this" {
  for_each = toset(local.nat_azs)

  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.public[each.key].id

  tags = merge(var.tags, { Name = "${var.name}-nat-${each.key}" })

  # A NAT gateway can only work once the internet gateway is attached. Terraform cannot see that dependency from the
  # arguments alone (nothing here refers to the IGW), so we state it. This is what depends_on is for.
  depends_on = [aws_internet_gateway.this]
}

# ---------------------------------------------------------------------------------------------------------------
# Routing: who may talk to what
# ---------------------------------------------------------------------------------------------------------------
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name}-public" })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# One private route table per zone, so that with nat_mode = "per_az" each zone uses its own NAT.
resource "aws_route_table" "private" {
  for_each = aws_subnet.private

  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name}-private-${each.key}" })
}

resource "aws_route" "private_nat" {
  # With nat_mode = "none" there is nothing to route to, so no route is created at all.
  for_each = var.nat_mode == "none" ? {} : aws_route_table.private

  route_table_id         = each.value.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[local.nat_for_az[each.key]].id
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}

# The database tier has a route table with NO default route: the databases cannot reach the internet, and the
# internet cannot reach them. That is a property of the network, not of a rule someone might forget to add.
resource "aws_route_table" "database" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name}-database" })
}

resource "aws_route_table_association" "database" {
  for_each = aws_subnet.database

  subnet_id      = each.value.id
  route_table_id = aws_route_table.database.id
}

# ---------------------------------------------------------------------------------------------------------------
# Private paths to AWS services
# ---------------------------------------------------------------------------------------------------------------
# A gateway endpoint for S3 is free. Container image layers live in S3, so without it every image pull would cross
# the (paid, per-GB) NAT gateway.
resource "aws_vpc_endpoint" "s3" {
  count = var.enable_s3_endpoint ? 1 : 0

  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat([for rt in aws_route_table.private : rt.id], [aws_route_table.database.id])

  tags = merge(var.tags, { Name = "${var.name}-s3" })
}

resource "aws_security_group" "endpoints" {
  count = length(var.interface_endpoints) > 0 ? 1 : 0

  name        = "${var.name}-vpc-endpoints"
  description = "HTTPS from inside the VPC to the interface endpoints"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTPS from the VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.cidr_block]
  }

  tags = merge(var.tags, { Name = "${var.name}-vpc-endpoints" })

  # Replace-before-destroy: a security group in use cannot be deleted, so a replacement is created first.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = toset(var.interface_endpoints)

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [for s in aws_subnet.private : s.id]
  security_group_ids  = [aws_security_group.endpoints[0].id]
  private_dns_enabled = true # the normal service name (sqs.<region>.amazonaws.com) now resolves to the private address

  tags = merge(var.tags, { Name = "${var.name}-${replace(each.key, ".", "-")}" })
}

# ---------------------------------------------------------------------------------------------------------------
# Flow logs (optional): who connected to what, accepted or rejected
# ---------------------------------------------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "flow" {
  count = var.enable_flow_logs ? 1 : 0

  name              = "/vpc/${var.name}/flow-logs"
  retention_in_days = var.flow_logs_retention_days

  tags = var.tags
}

data "aws_iam_policy_document" "flow_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flow" {
  count = var.enable_flow_logs ? 1 : 0

  name               = "${var.name}-vpc-flow-logs"
  assume_role_policy = data.aws_iam_policy_document.flow_assume.json

  tags = var.tags
}

data "aws_iam_policy_document" "flow_write" {
  count = var.enable_flow_logs ? 1 : 0

  # Least privilege: write to this one log group, nothing else.
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.flow[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "flow" {
  count = var.enable_flow_logs ? 1 : 0

  name   = "write-flow-logs"
  role   = aws_iam_role.flow[0].id
  policy = data.aws_iam_policy_document.flow_write[0].json
}

resource "aws_flow_log" "this" {
  count = var.enable_flow_logs ? 1 : 0

  vpc_id               = aws_vpc.this.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow[0].arn
  iam_role_arn         = aws_iam_role.flow[0].arn

  tags = merge(var.tags, { Name = "${var.name}-flow-logs" })
}
