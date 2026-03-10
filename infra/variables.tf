variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}

variable "hdns_token" {
  description = "Hetzner DNS API token"
  type        = string
  sensitive   = true
}

variable "server_name" {
  description = "Name of the Hetzner server"
  type        = string
  default     = "mitty"
}

variable "server_type" {
  description = "Hetzner server type (e.g. cx22, cx32)"
  type        = string
  default     = "cx22"
}

variable "server_location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "fsn1"
}

variable "server_image" {
  description = "OS image for the server"
  type        = string
  default     = "ubuntu-24.04"
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key to register"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "domain" {
  description = "Domain name for the application (e.g. mitty.example.com)"
  type        = string
}

variable "zone_name" {
  description = "DNS zone name (e.g. example.com)"
  type        = string
}

variable "ssh_allowed_ips" {
  description = "IP ranges allowed to SSH into the server. Restrict to your IP for security."
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}
