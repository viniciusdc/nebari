# Pre-create secret for git-sync ssh key, should be updated with new key if changed
resource "kubernetes_secret" "keycloak-git-sync-ssh-key" {
  metadata {
    name      = "keycloak-git-sync-ssh-key"
    namespace = var.namespace
  }
  data = {
    "ssh-privatekey" = var.custom_theme_config.ssh_key != null ? filebase64(var.custom_theme_config.ssh_key.path) : ""
    "known_hosts"    = var.custom_theme_config.ssh_key != null ? filebase64(var.custom_theme_config.ssh_key.known_hosts_path) : ""
  }
}

locals {
  extraInitContainers = var.custom_theme_config.repository_url != null ? yamlencode([
    local.keycloak_base_jar_container,
    {
      name  = "keycloak-git-sync"
      image = "k8s.gcr.io/git-sync:v3.1.5"
      volumeMounts = [
        {
          name      = "custom-themes"
          mountPath = "/opt/data/custom-themes"
        },
        {
          name      = "keycloak-git-sync-ssh-key"
          mountPath = "/etc/git-secret"
        }

      ]
      securityContext = {
        runAsUser = 0
      }
      env = [
        {
          name  = "GIT_SYNC_REPO"
          value = var.custom_theme_config.repository_url
        },
        {
          name  = "GIT_SYNC_BRANCH"
          value = var.custom_theme_config.repository_branch != null ? var.custom_theme_config.repository_branch : "main"
        },
        {
          name  = "GIT_SYNC_ONE_TIME"
          value = "true"
        },
        {
          name  = "GIT_SYNC_GROUP_WRITE"
          value = "true"
        },
        {
          name  = "GIT_SYNC_ROOT"
          value = "/opt/data/custom-themes"
        },
        {
          name  = "GIT_SYNC_DEST"
          value = "themes"
        },
        {
          name  = "GIT_SYNC_SSH"
          value = var.custom_theme_config.ssh_key != null ? "true" : "false"
      }]
    }
    ]) : yamlencode([
    local.keycloak_base_jar_container
  ])
}
