# =============================================================================
# Security Groups
# =============================================================================
# EC2 API prod security group (sg-0edf5ab745a438dd2)
# Rules:
#   Inbound: 80 (HTTP) + 443 (HTTPS) from 0.0.0.0/0; 22 (SSH) restricted IPs
#   Outbound: all traffic
#
# NOTE: SSH inbound CIDR (var.ssh_allowed_cidrs) should be set to actual
# restricted IP ranges. Default is empty (no SSH from this Terraform definition).
# The existing rule in AWS may have specific IPs already — do NOT overwrite without
# verifying: aws ec2 describe-security-groups --group-ids sg-0edf5ab745a438dd2
# =============================================================================

variable "ssh_allowed_cidrs" {
  description = "CIDR blocks allowed to SSH into the API EC2 instance (port 22). Keep restricted."
  type        = list(string)
  # TODO: set to actual restricted IP ranges, e.g. ["<your-office-ip>/32", "<vpn-ip>/32"]
  default = []
}

resource "aws_security_group" "api" {
  name        = "auraxis-api-prod-sg"
  description = "Security group for auraxis API EC2 prod instance"
  # TODO: set vpc_id to the actual VPC ID
  # vpc_id = "<vpc-id>"

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = length(var.ssh_allowed_cidrs) > 0 ? [1] : []
    content {
      description = "SSH (restricted)"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.ssh_allowed_cidrs
    }
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "auraxis-api-prod-sg"
  }
}
