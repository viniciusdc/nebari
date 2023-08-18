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
    storage_class_name = "default"
  }
}

resource "kubernetes_pod" "keycloak-clone-git-themes-repo" {
  count = local.enable_custom_themes

  metadata {
    name = "keycloak-git-clone-themes-pod"
  }

  spec {
    init_container {
      name  = "git-clone"
      image = "git/git:latest"

      volume_mount {
        name       = "keycloak-git-clone-repo-pv"
        mount_path = "/themes"
      }

      volume_mount {
        name       = "ssh-secret"
        mount_path = "/root/.ssh"
      }

      command = ["git", "clone", var.custom_theme_config.repo, "/themes"]
    }

    volume {
      name = "keycloak-git-clone-repo-pv"
      persistent_volume_claim {
        claim_name = kubernetes_persistent_volume_claim.keycloak-git-clone-repo-pvc[count.index].*.metadata.0.name
      }
    }

    volume {
      name = "ssh-secret"
      secret {
        secret_name = kubernetes_secret.keycloak-git-ssh-secret[count.index].metadata.0.name
      }
    }
  }
}

locals {
  enable_custom_themes = var.custom_theme_config != null ? 1 : 0
}
