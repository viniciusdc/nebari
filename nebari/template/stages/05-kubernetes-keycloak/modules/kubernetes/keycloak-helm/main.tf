terraform {
  # Optional attributes and the defaults function are # both
  # experimental, so we must opt in to the experiment.
  experiments = [module_variable_optional_attrs]
}

locals {
  keycloak_custom_themes_config = var.custom_theme_config != null ? jsonencode({
    extraInitContainers = [
      {
        name  = "git-clone"
        image = "git/git:latest"
        command = [
          "git",
          "clone",
          var.custom_theme_config.repository_url,
          "/themes",
        ]
        volumeMounts = [
          {
            name      = "custom-themes"
            mountPath = "/themes"
          },
          {
            name      = "ssh-secret"
            mountPath = "/root/.ssh"
          }
        ]
      }
    ]
    extraVolumes = [
      {
        name = "custom-themes"
        persistentVolumeClaim = {
          claimName = "keycloak-git-clone-repo-pvc"
        }
      }
    ]
    extraVolumeMounts = [
      {
        name      = "custom-themes"
        mountPath = "/opt/jboss/keycloak/themes"
        subPath   = "themes"
      }
    ]
  }) : jsonencode({})
}

resource "helm_release" "keycloak" {
  name      = "keycloak"
  namespace = var.namespace

  repository = "https://codecentric.github.io/helm-charts"
  chart      = "keycloak"
  version    = "15.0.2"

  values = concat([
    # https://github.com/codecentric/helm-charts/blob/keycloak-15.0.2/charts/keycloak/values.yaml
    file("${path.module}/values.yaml"),
    jsonencode({
      nodeSelector = {
        "${var.node-group.key}" = var.node-group.value
      }
      postgresql = {
        primary = {
          nodeSelector = {
            "${var.node-group.key}" = var.node-group.value
          }
        }
      }
    }),
    local.keycloak_custom_themes_config,
  ], var.overrides)

  set {
    name  = "nebari_bot_password"
    value = var.nebari-bot-password
  }

  set {
    name  = "initial_root_password"
    value = var.initial-root-password
  }
}


resource "kubernetes_manifest" "keycloak-http" {
  manifest = {
    apiVersion = "traefik.containo.us/v1alpha1"
    kind       = "IngressRoute"
    metadata = {
      name      = "keycloak-http"
      namespace = var.namespace
    }
    spec = {
      entryPoints = ["websecure"]
      routes = [
        {
          kind  = "Rule"
          match = "Host(`${var.external-url}`) && PathPrefix(`/auth`) "
          services = [
            {
              name = "keycloak-headless"
              # Really not sure why 8080 works here
              port      = 80
              namespace = var.namespace
            }
          ]
        }
      ]
    }
  }
}
