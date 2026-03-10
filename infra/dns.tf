data "hetznerdns_zone" "main" {
  name = var.zone_name
}

resource "hetznerdns_record" "app" {
  zone_id = data.hetznerdns_zone.main.id
  name    = var.domain == var.zone_name ? "@" : replace(var.domain, ".${var.zone_name}", "")
  type    = "A"
  value   = hcloud_server.mitty.ipv4_address
  ttl     = 300
}
