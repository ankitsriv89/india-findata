# =============================================================================
# spot.tf — optional spot instance configuration for 70% cost reduction
# =============================================================================
#
# Use this INSTEAD of the aws_instance in main.tf for cheapest testing.
#
# Spot pricing (ap-south-1, June 2026, approximate):
#   t3.small spot:  ~$0.007/hr = ~$5/month
#   t3.medium spot: ~$0.013/hr = ~$9/month  (recommended if CPI runs OOM)
#
# WARNING: Spot instances can be interrupted with 2-minute notice.
#   - ClickHouse and PostgreSQL write to the data EBS volume (survives)
#   - Any in-progress pipeline run will be lost (retry on next schedule)
#   - For testing this is fine. For production, use on-demand or reserved.
#
# To use: set variable use_spot = true in terraform.tfvars

variable "use_spot" {
  description = "Use spot instance for ~70% cost reduction (interruptible)"
  type        = bool
  default     = false
}

variable "spot_max_price" {
  description = "Maximum spot price per hour (USD). Set to on-demand price as a ceiling."
  type        = string
  default     = "0.023"  # t3.small on-demand price in ap-south-1
}

# Uncomment and use this resource instead of aws_instance in main.tf for spot:
#
# resource "aws_spot_instance_request" "findata_spot" {
#   count = var.use_spot ? 1 : 0
#
#   ami                    = data.aws_ami.al2023.id
#   instance_type          = var.instance_type
#   key_name               = var.key_name
#   subnet_id              = tolist(data.aws_subnets.default.ids)[0]
#   vpc_security_group_ids = [aws_security_group.findata.id]
#   spot_price             = var.spot_max_price
#   wait_for_fulfillment   = true
#
#   root_block_device {
#     volume_type = "gp3"
#     volume_size = 16
#   }
#
#   user_data = base64encode(templatefile("${path.module}/user_data.sh", {
#     project_name = var.project_name
#     data_device  = "/dev/xvdf"
#   }))
#
#   tags = { Name = "${var.project_name}-spot", Project = var.project_name }
# }
