variable "account_id" {
  type = string
}

variable "cloudflare_api_token" {
  type      = string
  sensitive = true
}

variable "zone_id" {
  type = string
}

variable "forwarding_rules" {
  description = "Map of alias to destination (1-to-1). Example: { 'hello' = 'me@fastmail.com' }"
  type        = map(string)
}

variable "maintainer_emails" {
  description = "List of emails that receive the 'maintainers@' broadcast"
  type        = list(string)
}

variable "vscode_marketplace_verification_code" {
  description = "TXT record content for VS Code Marketplace domain verification"
  type        = string
  sensitive   = false
}