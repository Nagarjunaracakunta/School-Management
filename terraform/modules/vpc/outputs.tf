output "vpc_id" {
  description = "Id of the VPC."
  value       = aws_vpc.this.id
}

output "vpc_cidr_block" {
  description = "Address range of the VPC."
  value       = aws_vpc.this.cidr_block
}

output "azs" {
  description = "Availability zones in use, in the same order as the subnet lists."
  value       = var.azs
}

output "public_subnet_ids" {
  description = "Public subnets (load balancers, NAT gateways), in zone order."
  value       = [for az in var.azs : aws_subnet.public[az].id]
}

output "private_subnet_ids" {
  description = "Private subnets (Kubernetes nodes and pods), in zone order."
  value       = [for az in var.azs : aws_subnet.private[az].id]
}

output "database_subnet_ids" {
  description = "Database subnets (RDS), in zone order."
  value       = [for az in var.azs : aws_subnet.database[az].id]
}

output "nat_public_ips" {
  description = "Public addresses the platform uses when it calls the internet (give these to partners who allow-list by IP)."
  value       = [for eip in aws_eip.nat : eip.public_ip]
}

output "private_route_table_ids" {
  description = "Private route tables, by zone."
  value       = { for az, rt in aws_route_table.private : az => rt.id }
}
