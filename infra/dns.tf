resource "dnsimple_zone_record" "app" {
  zone_name = var.zone_name
  name      = var.domain == var.zone_name ? "" : replace(var.domain, ".${var.zone_name}", "")
  type      = "A"
  value     = hcloud_server.mitty.ipv4_address
  ttl       = 300
}
