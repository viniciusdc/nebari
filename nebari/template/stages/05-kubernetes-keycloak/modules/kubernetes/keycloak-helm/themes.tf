
# create kubernetes secret for ssh key to be mounted at init container later
resource "kubernetes_secret" "keycloak-git-clone-repo-ssh-key" {
  metadata {
    name      = "keycloak-git-clone-repo-ssh-key"
    namespace = var.namespace
  }
  data = {
    "keycloak-theme-ssh.pem" = local.ssh_key_enabled != null ? file("${local.ssh_key_enabled}") : ""
    type                     = "Opaque"
  }
}

resource "kubernetes_config_map" "update-git-clone-repo" {
  metadata {
    name      = "update-git-clone-repo"
    namespace = var.namespace
  }
  data = {
    "update-git-clone-repo.sh" = file("${path.module}/files/theme-repo-clonning.sh")
  }
}

resource "kubernetes_persistent_volume_claim" "keycloak-git-clone-repo-pvc" {
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
  ssh_key_enabled      = try(length(var.custom_theme_config), 0) > 0 ? var.custom_theme_config.ssh_key : null
}
