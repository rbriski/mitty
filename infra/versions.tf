terraform {
  required_version = ">= 1.5"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.60"
    }
    dnsimple = {
      source  = "dnsimple/dnsimple"
      version = "~> 1.7"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

provider "dnsimple" {
  token   = var.dnsimple_token
  account = var.dnsimple_account_id
}
