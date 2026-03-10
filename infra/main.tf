resource "hcloud_ssh_key" "default" {
  name       = "${var.server_name}-key"
  public_key = file(var.ssh_public_key_path)
}

resource "hcloud_firewall" "default" {
  name = "${var.server_name}-fw"

  # SSH — restricted by ssh_allowed_ips
  dynamic "rule" {
    for_each = var.ssh_allowed_ips
    content {
      direction  = "in"
      protocol   = "tcp"
      port       = "22"
      source_ips = [rule.value]
    }
  }

  # HTTP
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # HTTPS
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # ICMP (IPv4)
  rule {
    direction  = "in"
    protocol   = "icmp"
    source_ips = ["0.0.0.0/0"]
  }

  # ICMP (IPv6)
  rule {
    direction  = "in"
    protocol   = "icmp"
    source_ips = ["::/0"]
  }
}

resource "hcloud_server" "mitty" {
  name        = var.server_name
  server_type = var.server_type
  location    = var.server_location
  image       = var.server_image
  user_data   = file("${path.module}/cloud-init.yaml")

  ssh_keys = [hcloud_ssh_key.default.id]

  firewall_ids = [hcloud_firewall.default.id]

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }
}
