# =============================================================================
# spot.tf — spot instance variables for ~70% cost reduction
# =============================================================================
#
# The actual spot configuration lives on aws_instance.findata in main.tf via a
# dynamic instance_market_options block, gated on var.use_spot. This file only
# declares the toggle + price ceiling. (Earlier versions used a separate
# aws_spot_instance_request resource; instance_market_options is the modern way
# and keeps the EBS/EIP wiring in main.tf intact regardless of spot vs on-demand.)
#
# Spot pricing (ap-south-1, June 2026, approximate):
#   t3.small spot:  ~$0.007/hr = ~$5/month
#   t3.medium spot: ~$0.013/hr = ~$9/month  (recommended if CPI runs OOM)
#
# WARNING: Spot instances can be interrupted with 2-minute notice.
#   - interruption_behavior = "stop" means the instance stops (not terminates)
#   - ClickHouse and PostgreSQL write to the data EBS volume (survives stop)
#   - Any in-progress pipeline run is lost (retries on next schedule)
#   - For testing this is fine. For production, use on-demand or reserved.
#
# To use: set use_spot = true in terraform.tfvars

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
