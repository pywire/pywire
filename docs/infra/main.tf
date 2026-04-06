terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# --- 1. The Documentation Site (Project A) ---
# Connects to the 'pywire/pywire' repo
resource "cloudflare_pages_project" "docs" {
  account_id        = var.account_id
  name              = "pywire-docs"
  production_branch = "main"

  source = {
    type = "github"
    config = {
      owner                          = "pywire"
      repo_name                      = "pywire"
      production_branch              = "main"
      production_deployments_enabled = false
      preview_deployment_setting     = "none"
    }
  }

  build_config = {
    root_dir        = "docs"
    build_command   = "pnpm run build"
    destination_dir = "dist"
  }
}

resource "cloudflare_pages_project" "landing" {
  account_id        = var.account_id
  name              = "pywire-landing"
  production_branch = "main"

  source = {
    type = "github"
    config = {
      owner                          = "pywire"
      repo_name                      = "pywire.dev"
      production_branch              = "main"
      production_deployments_enabled = false
      preview_deployment_setting     = "none"
    }
  }

  build_config = {
    root_dir        = "site"
    build_command   = "pnpm run build"
    destination_dir = "dist"
  }
}

# --- 3. The Router (Worker) ---
resource "cloudflare_workers_script" "router" {
  account_id     = var.account_id
  script_name    = "pywire-router"
  content_file   = "../worker/src/index.js"
  content_sha256 = filesha256("../worker/src/index.js")
  main_module    = "index.js"
}

# --- Nightly Environment ---
# 1. DNS Record
resource "cloudflare_dns_record" "nightly" {
  zone_id = var.zone_id
  name    = "nightly"
  content = cloudflare_pages_project.landing.subdomain
  type    = "CNAME"
  proxied = true
  ttl     = 1
}

# --- VS Code Marketplace Domain Verification ---
resource "cloudflare_dns_record" "vscode_verification" {
  zone_id = var.zone_id
  name    = "_visual-studio-marketplace-pywire"
  content = var.vscode_marketplace_verification_code
  type    = "TXT"
  ttl     = 3600
}




# --- 4. The DNS & Routing ---
resource "cloudflare_workers_route" "catch_all" {
  zone_id = var.zone_id
  pattern = "pywire.dev/*"
  script  = cloudflare_workers_script.router.script_name
}

resource "cloudflare_workers_route" "nightly" {
  zone_id = var.zone_id
  pattern = "nightly.pywire.dev/*"
  script  = cloudflare_workers_script.router.script_name
}

# --- 5. Email Routing Setup ---

resource "cloudflare_email_routing_settings" "main" {
  zone_id = var.zone_id
}



# Destination Registration
# Helper to find every unique email address across both variables
locals {
  all_unique_emails = distinct(concat(
    values(var.forwarding_rules),
    var.maintainer_emails
  ))
}

# Register every email found in your variables
resource "cloudflare_email_routing_address" "destinations" {
  for_each   = toset(local.all_unique_emails)
  account_id = var.account_id
  email      = each.value
}

# Individual Rules
resource "cloudflare_email_routing_rule" "individual_aliases" {
  for_each = var.forwarding_rules

  zone_id = var.zone_id
  name    = "Forward: ${each.key}@"
  enabled = true

  matchers = [{
    type  = "literal"
    field = "to"
    value = "${each.key}@pywire.dev"
  }]

  actions = [{
    type = "forward"
    # Look up the verified address resource
    value = [cloudflare_email_routing_address.destinations[each.value].email]
  }]
}

# The Maintainers Group Rule
resource "cloudflare_email_routing_rule" "maintainers_group" {
  zone_id = var.zone_id
  name    = "Group: Maintainers"
  enabled = true

  matchers = [{
    type  = "literal"
    field = "to"
    value = "maintainers@pywire.dev"
  }]

  actions = [{
    type = "forward"
    # Dynamically grab the verified email ID for everyone in the list
    value = [
      for email in var.maintainer_emails :
      cloudflare_email_routing_address.destinations[email].email
    ]
  }]
}
