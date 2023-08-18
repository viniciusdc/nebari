resource "kubernetes_secret" "keycloak-git-ssh-secret" {
    count = var.keycloak_custom_themes.ssh_key != null ? 1 : 0

    metadata {
        name      = "keycloak-git-ssh-secret"
        namespace = var.namespace
    }

    data = {
        # assuming the private key was base64 encoded
        "id_rsa" = var.keycloak_custom_themes.ssh_key
  }
}

resource "kubernetes_persistent_volume" "keycloak-git-clone-repo-pv" {
  count = var.keycloak_custom_themes.repo != null ? 1 : 0

  metadata {
    name = "keycloak-git-clone-repo-pv"
  }

  spec {
    access_modes = ["ReadWriteOnce"]
    capacity {
      storage = "10Gi"
    }
    persistent_volume_reclaim_policy = "Retain"

    host_path {
      path = "/themes"
    }
  }
}

resource "kubernetes_persistent_volume_claim" "keycloak-git-clone-repo-pvc" {
  count = var.keycloak_custom_themes.repo != null ? 1 : 0

  metadata {
    name      = "keycloak-git-clone-repo-pvc"
    namespace = var.namespace
  }

  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = "10Gi"
      }
    }

    volume_name = kubernetes_persistent_volume.keycloak-git-clone-repo-pv.*.metadata.0.name
  }
}

resource "kubernetes_pod" "keycloak-clone-git-themes-repo" {
  count = var.keycloak_custom_themes.repo != null ? 1 : 0

  metadata {
    name = "keycloak-git-clone-themes-pod"
  }

  restart_policy = "Never"

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

      command = ["git", "clone", var.keycloak_custom_themes.repo, "/themes"]
    }

    volume {
      name = "keycloak-git-clone-repo-pv"
      persistent_volume_claim {
        claim_name = kubernetes_persistent_volume_claim.keycloak-git-clone-repo-pvc.*.metadata.0.name
      }
    }

    volume {
      name = "ssh-secret"
      secret {
        secret_name = kubernetes_secret.keycloak-git-ssh-secret.metadata.0.name
      }
    }
  }
}
