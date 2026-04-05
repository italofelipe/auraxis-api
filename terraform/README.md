# Terraform — Auraxis Web Infrastructure

IaC for existing AWS resources that were created manually.
Manages the S3 + CloudFront + Route53 + Security Group stack for `app.auraxis.com.br`.

## Backend

State is stored in S3:

- **Bucket:** `auraxis-infra-state`
- **Key:** `web/terraform.tfstate`
- **Region:** `us-east-1`
- **Encryption:** enabled (SSE-S3)

## Resources under management

| Resource | ID / Name |
|:---------|:----------|
| `aws_s3_bucket.web` | `app.auraxis.com.br` |
| `aws_s3_bucket_public_access_block.web` | `app.auraxis.com.br` |
| `aws_s3_bucket_policy.web` | `app.auraxis.com.br` |
| `aws_cloudfront_origin_access_control.web` | `E1OIWI7M3IH8V4` (`auraxis-web-oac`) |
| `aws_cloudfront_distribution.web` | `E38WVQOCDQADWB` |
| `aws_cloudfront_response_headers_policy.web_security` | `8078897a-1312-4e87-8730-4c959789ecde` |
| `aws_route53_record.app` | `app.auraxis.com.br` A → CloudFront |
| `aws_route53_record.api` | `api.auraxis.com.br` A → EC2 EIP |
| `aws_security_group.api` | `sg-0edf5ab745a438dd2` |

## Prerequisites

Before running `terraform init && terraform apply`, fill in the TODOs:

1. **Route53 hosted zone ID** — retrieve and set `var.route53_zone_id`:

   ```bash
   aws route53 list-hosted-zones \
     --query 'HostedZones[?Name==`auraxis.com.br.`].Id' \
     --output text
   ```

2. **ACM certificate ARN** — set `var.acm_certificate_arn`:

   ```bash
   aws acm list-certificates --region us-east-1 \
     --query 'CertificateSummaryList[?DomainName==`*.auraxis.com.br`].CertificateArn' \
     --output text
   ```

3. **Update `import.tf`** — replace the placeholder zone ID `Z000000000000000000000`
   with the real Route53 zone ID in the two Route53 import blocks.

4. **SSH CIDR rules** — review and set `var.ssh_allowed_cidrs` in `security.tf`
   to match the actual inbound rules on the security group.

## Usage

```bash
# Initialize with S3 backend
terraform init

# Preview import + plan (no changes applied)
terraform plan

# Apply import + reconcile any drift
terraform apply
```

## File structure

| File | Purpose |
|:-----|:--------|
| `main.tf` | Provider + S3 backend configuration |
| `variables.tf` | Input variables with defaults |
| `outputs.tf` | Outputs: bucket_name, distribution_id, domain_name, etc. |
| `web.tf` | S3 bucket + CloudFront OAC + distribution + response headers policy |
| `dns.tf` | Route53 A records for app and api subdomains |
| `security.tf` | EC2 security group for the API instance |
| `import.tf` | Terraform 1.5+ declarative import blocks |

## Drift detection

After import, run `terraform plan` to verify zero drift. Any non-empty plan
indicates configuration drift — investigate before applying.

The CI workflow `aws-infra-drift.yml` runs `terraform plan` on a schedule and
alerts on drift.

## Outputs consumed by CI

| Output | Used in |
|:-------|:--------|
| `bucket_name` | `S3_BUCKET` in `deploy.yml` (auraxis-web) |
| `distribution_id` | `AWS_WEB_CLOUDFRONT_DISTRIBUTION_ID` in `deploy.yml` |
