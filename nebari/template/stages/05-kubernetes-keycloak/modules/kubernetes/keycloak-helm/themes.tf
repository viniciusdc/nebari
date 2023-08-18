resource "kubernetes_secret" "keycloak-git-ssh-secret" {
  count = var.custom_theme_config != null ? 1 : 0

  metadata {
    name      = "keycloak-git-ssh-secret"
    namespace = var.namespace
  }

  data = {
    # assuming the private key was base64 encoded
    "id_rsa" = var.custom_theme_config.ssh_key
  }
}

resource "kubernetes_persistent_volume_claim" "keycloak-git-clone-repo-pvc" {
  count = local.enable_custom_themes

  metadata {
    name      = "keycloak-git-clone-repo-pvc"
    namespace = var.namespace

    labels = {
      "app"        = "keycloak-git-clone-repo-pvc"
      "managed-by" = "keycloak"
    }
  }

  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = "4Gi"
      }
    }
    storage_class_name = "standard"
  }
}

locals {
  enable_custom_themes = var.custom_theme_config != null ? 1 : 0
}
