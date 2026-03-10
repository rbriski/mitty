# Local backend for now. Uncomment the S3 block below after creating
# the mitty-tfstate bucket in Hetzner Object Storage, then run:
#   terraform init -migrate-state

# terraform {
#   backend "s3" {
#     bucket = "mitty-tfstate"
#     key    = "terraform.tfstate"
#     region = "fsn1"
#
#     endpoints = {
#       s3 = "https://fsn1.your-objectstorage.com"
#     }
#
#     # Hetzner Object Storage does not support these features
#     skip_credentials_validation = true
#     skip_metadata_api_check     = true
#     skip_region_validation      = true
#     skip_requesting_account_id  = true
#     skip_s3_checksum            = true
#   }
# }
