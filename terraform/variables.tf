variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (prod, staging)"
  type        = string
  default     = "prod"
}

variable "project" {
  description = "Project name used for tagging"
  type        = string
  default     = "auraxis"
}

variable "web_bucket_name" {
  description = "S3 bucket name for the frontend (app.auraxis.com.br)"
  type        = string
  default     = "app.auraxis.com.br"
}

variable "cloudfront_distribution_id" {
  description = "Existing CloudFront distribution ID"
  type        = string
  default     = "E38WVQOCDQADWB"
}

variable "cloudfront_oac_id" {
  description = "Existing CloudFront Origin Access Control ID"
  type        = string
  default     = "E1OIWI7M3IH8V4"
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID for auraxis.com.br"
  type        = string
  # TODO: replace with actual hosted zone ID from `aws route53 list-hosted-zones`
  default = ""
}

variable "ec2_eip_api" {
  description = "Elastic IP address for the API EC2 instance (prod)"
  type        = string
  default     = "100.49.10.188"
}

variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate for *.auraxis.com.br (must be in us-east-1 for CloudFront)"
  type        = string
  # TODO: replace with actual ACM certificate ARN from `aws acm list-certificates --region us-east-1`
  default = ""
}

variable "security_group_id" {
  description = "Security group ID for the API EC2 instance"
  type        = string
  default     = "sg-0edf5ab745a438dd2"
}
