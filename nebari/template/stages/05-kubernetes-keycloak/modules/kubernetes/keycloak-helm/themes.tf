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


resource "kubernetes_job" "git_clone_job" {
  count = local.enable_custom_themes

  metadata {
    name      = "git-clone-job"
    namespace = var.namespace
  }

  spec {
    backoff_limit = 0

    template {
      metadata {
        name = "git-clone-job"
        labels = {
          "app"        = "git-clone-job"
          "managed-by" = "keycloak"
        }
      }

      spec {
        restart_policy = "Never"

        container {
          name  = "git-clone"
          image = "git/git:latest"

          volume_mount {
            name       = "custom-themes"
            mount_path = "/themes"
          }

          dynamic "volume_mount" {
            for_each = var.custom_theme_config.ssh_key != null ? [1] : []
            content {
              name       = "ssh-secret"
              mount_path = "/root/.ssh"
              read_only  = true
            }
          }

          command = [
            "sh",
            "-c",
            "if [ ! -d /themes/.git ]; then git clone ${var.custom_theme_config.repository_url} /themes; else git -C /themes pull; fi"
          ]
        }

        volume {
          name = "custom-themes"
          persistent_volume_claim {
            claim_name = "keycloak-git-clone-repo-pvc"
          }
        }

        dynamic "volume" {
          for_each = var.custom_theme_config.ssh_key != null ? [1] : []
          content {
            name = "ssh-secret"
            secret {
              secret_name = "keycloak-git-ssh-secret"
            }
          }
        }
      }
    }
  }
}




locals {
  enable_custom_themes = var.custom_theme_config != null ? 1 : 0
}
