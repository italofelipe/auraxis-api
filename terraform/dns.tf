# =============================================================================
# Route53 — DNS records
# =============================================================================
# Infra map: 1 hosted zone for auraxis.com.br (Route53)
# API record: api.auraxis.com.br A → EC2 EIP 100.49.10.188
# Web record: app.auraxis.com.br CNAME/ALIAS → CloudFront E38WVQOCDQADWB
#
# NOTE: var.route53_zone_id must be set before running `terraform import`.
# Retrieve via: aws route53 list-hosted-zones --query 'HostedZones[?Name==`auraxis.com.br.`].Id'
# =============================================================================

# app.auraxis.com.br → CloudFront (ALIAS)
resource "aws_route53_record" "app" {
  zone_id = var.route53_zone_id
  name    = "app.auraxis.com.br"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
    evaluate_target_health = false
  }
}

# api.auraxis.com.br → EC2 EIP (A record)
resource "aws_route53_record" "api" {
  zone_id = var.route53_zone_id
  name    = "api.auraxis.com.br"
  type    = "A"
  ttl     = 300

  records = [var.ec2_eip_api]
}
