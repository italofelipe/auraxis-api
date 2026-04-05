output "bucket_name" {
  description = "S3 bucket name for the frontend"
  value       = aws_s3_bucket.web.bucket
}

output "bucket_arn" {
  description = "S3 bucket ARN for the frontend"
  value       = aws_s3_bucket.web.arn
}

output "distribution_id" {
  description = "CloudFront distribution ID"
  value       = aws_cloudfront_distribution.web.id
}

output "distribution_domain_name" {
  description = "CloudFront distribution domain name"
  value       = aws_cloudfront_distribution.web.domain_name
}

output "distribution_arn" {
  description = "CloudFront distribution ARN"
  value       = aws_cloudfront_distribution.web.arn
}

output "oac_id" {
  description = "CloudFront Origin Access Control ID"
  value       = aws_cloudfront_origin_access_control.web.id
}
