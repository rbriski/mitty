output "server_ip" {
  description = "Public IPv4 address of the server"
  value       = hcloud_server.mitty.ipv4_address
}

output "ssh_command" {
  description = "SSH command to connect to the server"
  value       = "ssh deploy@${hcloud_server.mitty.ipv4_address}"
}

output "domain" {
  description = "Domain name for the application"
  value       = var.domain
}
