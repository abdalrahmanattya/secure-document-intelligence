variable "aws_region" {
  type    = string
  default = "eu-west-1"
}

variable "project_name" {
  type    = string
  default = "secure-document-intelligence"
}

variable "enable_expensive_ai" {
  type        = bool
  default     = false
  description = "Enable Bedrock/Textract integrations only during an approved smoke run."
}

variable "state_bucket" {
  type        = string
  default     = ""
  description = "Protected remote-state bucket supplied by deployment workflow."
}
variable "state_key" {
  type    = string
  default = "secure-document-intelligence/terraform.tfstate"
}
variable "state_lock_table" {
  type        = string
  default     = ""
  description = "Protected DynamoDB lock table supplied by deployment workflow."
}
variable "bedrock_model_id" {
  type    = string
  default = "amazon.nova-lite-v1:0"
}
variable "ui_callback_url" {
  type        = string
  default     = "http://localhost:5173/"
  description = "Cognito PKCE callback; workflow sets this to the Terraform-derived CloudFront URL before the final apply."
}
