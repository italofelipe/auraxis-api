# =============================================================================
# S3 — Frontend bucket (app.auraxis.com.br)
# =============================================================================

resource "aws_s3_bucket" "web" {
  bucket = var.web_bucket_name
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket = aws_s3_bucket.web.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

# Bucket policy: allow CloudFront OAC (SigV4) only
resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontOAC"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.web.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.web.arn
          }
        }
      }
    ]
  })
}

# =============================================================================
# CloudFront — Origin Access Control
# =============================================================================

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "auraxis-web-oac"
  description                       = "OAC for auraxis web S3 origin (SigV4)"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# =============================================================================
# CloudFront — Response Headers Policy (CSP + security headers)
# =============================================================================

resource "aws_cloudfront_response_headers_policy" "web_security" {
  name    = "auraxis-web-security-headers"
  comment = "CSP granular + security headers for auraxis web"

  security_headers_config {
    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }

    xss_protection {
      mode_block = true
      protection = true
      override   = true
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "camera=(), microphone=(), geolocation=()"
      override = true
    }
  }
}

# =============================================================================
# CloudFront — Distribution
# =============================================================================

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = ["app.auraxis.com.br"]
  price_class         = "PriceClass_100"
  comment             = "auraxis-web frontend (${var.environment})"

  origin {
    domain_name              = "${aws_s3_bucket.web.bucket}.s3.amazonaws.com"
    origin_id                = "S3-${aws_s3_bucket.web.bucket}"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    target_origin_id       = "S3-${aws_s3_bucket.web.bucket}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    response_headers_policy_id = aws_cloudfront_response_headers_policy.web_security.id

    # TODO: Replace with actual cache policy ID if a custom one is configured
    # Using CachingOptimized managed policy (658327ea-f89d-4fab-a63d-7e88639e58f6)
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    # TODO: Add CloudFront Function ARN for SSG router if it exists
    # function_association {
    #   event_type   = "viewer-request"
    #   function_arn = aws_cloudfront_function.ssg_router.arn
    # }
  }

  # SPA fallback: 403/404 from S3 → /index.html with HTTP 200
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    # TODO: set acm_certificate_arn variable with actual certificate ARN
    acm_certificate_arn      = var.acm_certificate_arn != "" ? var.acm_certificate_arn : null
    ssl_support_method       = var.acm_certificate_arn != "" ? "sni-only" : null
    minimum_protocol_version = var.acm_certificate_arn != "" ? "TLSv1.2_2021" : null

    # Fallback to CloudFront default certificate when ACM ARN not yet provided
    cloudfront_default_certificate = var.acm_certificate_arn == "" ? true : false
  }
}
