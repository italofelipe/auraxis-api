# =============================================================================
# Import blocks — Terraform 1.5+ declarative import syntax
# =============================================================================
# These blocks allow `terraform plan/apply` to import existing AWS resources
# into Terraform state idempotently, without running CLI `terraform import` commands.
#
# Prerequisites before running `terraform init && terraform apply`:
#   1. Set var.route53_zone_id to the actual hosted zone ID
#   2. Set var.acm_certificate_arn to the *.auraxis.com.br certificate ARN
#   3. Verify SSH CIDR rules in security.tf match the existing SG
#
# To retrieve missing values:
#   Zone ID:   aws route53 list-hosted-zones --query 'HostedZones[?Name==`auraxis.com.br.`]'
#   ACM ARN:   aws acm list-certificates --region us-east-1
#   Route53 A record ID format: <zone-id>_app.auraxis.com.br_A
# =============================================================================

# S3 bucket — frontend
import {
  to = aws_s3_bucket.web
  id = "app.auraxis.com.br"
}

# S3 public access block
import {
  to = aws_s3_bucket_public_access_block.web
  id = "app.auraxis.com.br"
}

# CloudFront Origin Access Control
import {
  to = aws_cloudfront_origin_access_control.web
  id = "E1OIWI7M3IH8V4"
}

# CloudFront distribution
import {
  to = aws_cloudfront_distribution.web
  id = "E38WVQOCDQADWB"
}

# CloudFront Response Headers Policy
import {
  to = aws_cloudfront_response_headers_policy.web_security
  id = "8078897a-1312-4e87-8730-4c959789ecde"
}

# Security Group — API EC2 prod
import {
  to = aws_security_group.api
  id = "sg-0edf5ab745a438dd2"
}

# Route53 record — app.auraxis.com.br (A / ALIAS to CloudFront)
# NOTE: ID format is <zone-id>_<name>_<type>
# TODO: replace Z000000000000000000000 with the actual hosted zone ID
import {
  to = aws_route53_record.app
  id = "Z000000000000000000000_app.auraxis.com.br_A"
}

# Route53 record — api.auraxis.com.br (A → EC2 EIP)
# TODO: replace Z000000000000000000000 with the actual hosted zone ID
import {
  to = aws_route53_record.api
  id = "Z000000000000000000000_api.auraxis.com.br_A"
}
