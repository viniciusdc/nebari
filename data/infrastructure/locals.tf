locals {
  additional_tags = {
    Project     = var.name
    Owner       = "terraform"
    Environment = var.environment
  }

  cluster_name = "${var.name}-${var.environment}"

  node_groups = {
    general = {
      key   = "kubernetes.io/os"
      value = "linux"

    }

    user = {
      key   = "kubernetes.io/os"
      value = "linux"

    }

    worker = {
      key   = "kubernetes.io/os"
      value = "linux"

    }
  }
}
