# =============================================================================
# main.tf — india-findata infrastructure on AWS (cheapest viable option)
# =============================================================================
#
# Architecture choice: single EC2 t3.small + EBS volume running Docker Compose.
#
# Why not managed services (RDS, ElastiCache, etc.)?
#   - ClickHouse is NOT available as a managed AWS service cheaply.
#     ClickHouse Cloud starts at ~$50/month. Self-hosted on EC2 = ~$0 extra.
#   - PostgreSQL via RDS db.t3.micro = ~$14/month. We run it in Docker = $0 extra.
#   - For testing this is the cheapest option that gives a real environment.
#
# Cost estimate (ap-south-1 / Mumbai, on-demand):
#   t3.small (2 vCPU, 2 GB RAM): ~$0.023/hr = ~$17/month
#   30 GB gp3 EBS volume:         ~$2.40/month
#   Elastic IP:                   $0 when attached to running instance
#   Data transfer (< 1 GB/month): ~$0.09/month
#   TOTAL:                        ~$20/month
#
# Cheaper option (spot instance, ~70% discount):
#   t3.small spot in ap-south-1:  ~$0.007/hr = ~$5/month
#   (see spot.tf for spot instance configuration)
#
# Cheapest possible for testing only:
#   t3.micro (1 vCPU, 1 GB RAM): ~$8/month on-demand
#   WARNING: ClickHouse needs ≥1.5 GB RAM. t3.micro will OOM under load.
#            Use t3.small (2 GB) as minimum for this stack.
#
# To deploy:
#   cd infra/terraform
#   terraform init
#   terraform plan -var="key_name=your-ec2-keypair"
#   terraform apply -var="key_name=your-ec2-keypair"
# =============================================================================

terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# =============================================================================
# Variables
# =============================================================================

variable "aws_region" {
  description = "AWS region. ap-south-1 (Mumbai) minimises latency for Indian data sources."
  type        = string
  default     = "ap-south-1"
}

variable "instance_type" {
  description = "EC2 instance type. t3.small is the minimum for this stack (ClickHouse needs ≥1.5 GB RAM)."
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Name to register the imported EC2 key pair under (see public_key_path)."
  type        = string
  default     = "india-findata-key"
}

variable "public_key_path" {
  description = "Path to the local SSH public key to import as the EC2 key pair."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "allowed_cidr" {
  description = "CIDR block allowed to reach the web UI and API. Default: open (restrict for production)."
  type        = string
  default     = "0.0.0.0/0"
}

variable "data_vol_size_gb" {
  description = "Size of the EBS data volume in GB. Holds Docker volumes (ClickHouse + Postgres data)."
  type        = number
  default     = 30
}

variable "project_name" {
  type    = string
  default = "india-findata"
}

# =============================================================================
# Data — latest Amazon Linux 2023 AMI
# =============================================================================

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# =============================================================================
# Networking — use default VPC to keep it simple
# =============================================================================

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# =============================================================================
# SSH Key Pair — import the local public key so we can SSH with the matching
# private key. AWS key_name must reference a registered key pair; importing
# here keeps the whole setup declarative (no manual console step).
# =============================================================================

resource "aws_key_pair" "findata" {
  key_name   = var.key_name
  public_key = file(pathexpand(var.public_key_path))
  tags       = { Name = var.project_name }
}

# =============================================================================
# Security Group
# =============================================================================

resource "aws_security_group" "findata" {
  name        = "${var.project_name}-sg"
  description = "india-findata: web dashboard + API access"
  vpc_id      = data.aws_vpc.default.id

  # Dashboard (nginx)
  ingress {
    description = "Web dashboard"
    from_port   = 5190
    to_port     = 5190
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  # FastAPI
  ingress {
    description = "FastAPI"
    from_port   = 8090
    to_port     = 8090
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  # Grafana
  ingress {
    description = "Grafana"
    from_port   = 3200
    to_port     = 3200
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  # SSH — restrict to your IP in production
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-sg" }
}

# =============================================================================
# EC2 Instance
# =============================================================================

resource "aws_instance" "findata" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.findata.key_name
  subnet_id              = tolist(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids = [aws_security_group.findata.id]

  # Spot instance request, toggled by var.use_spot (~70% cheaper, interruptible).
  # Using instance_market_options on a regular aws_instance is the modern AWS
  # approach — one resource, EBS/EIP wiring below stays intact regardless of mode.
  # "stop" interruption_behavior + persistent type means the instance stops (not
  # terminates) on interruption, so the data EBS volume and EIP survive and the
  # box can be restarted. dynamic{} emits the block only when use_spot is true.
  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        max_price                      = var.spot_max_price
        spot_instance_type             = "persistent"
        instance_interruption_behavior = "stop"
      }
    }
  }

  # Root volume: OS + Docker images (~16 GB is plenty)
  root_block_device {
    volume_type           = "gp3"
    volume_size           = 16
    delete_on_termination = true
    tags                  = { Name = "${var.project_name}-root" }
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    project_name = var.project_name
    data_device  = "/dev/xvdf"
  }))

  tags = { Name = var.project_name, Project = var.project_name }
}

# =============================================================================
# Data EBS Volume — separate from root so data survives instance replacement
# =============================================================================

resource "aws_ebs_volume" "data" {
  availability_zone = aws_instance.findata.availability_zone
  type              = "gp3"
  size              = var.data_vol_size_gb
  tags              = { Name = "${var.project_name}-data" }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.findata.id
}

# =============================================================================
# Elastic IP — stable public IP that survives instance stop/start
# =============================================================================

resource "aws_eip" "findata" {
  instance = aws_instance.findata.id
  domain   = "vpc"
  tags     = { Name = var.project_name }
}

# =============================================================================
# Outputs
# =============================================================================

output "public_ip" {
  description = "Elastic IP of the server"
  value       = aws_eip.findata.public_ip
}

output "dashboard_url" {
  description = "React dashboard URL"
  value       = "http://${aws_eip.findata.public_ip}:5190"
}

output "api_url" {
  description = "FastAPI base URL"
  value       = "http://${aws_eip.findata.public_ip}:8090"
}

output "grafana_url" {
  description = "Grafana URL"
  value       = "http://${aws_eip.findata.public_ip}:3200"
}

output "ssh_command" {
  description = "SSH into the server"
  value       = "ssh -i ${replace(var.public_key_path, ".pub", "")} ec2-user@${aws_eip.findata.public_ip}"
}
