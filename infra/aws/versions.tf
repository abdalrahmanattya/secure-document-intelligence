terraform {
  required_version = ">= 1.6.0"
  backend "s3" {}
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.80" }
    archive = { source = "hashicorp/archive", version = "~> 2.5" }
  }
}
provider "aws" { region = var.aws_region }
provider "archive" {}
