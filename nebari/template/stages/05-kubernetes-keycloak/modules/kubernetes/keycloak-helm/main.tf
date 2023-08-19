terraform {
  # Optional attributes and the defaults function are # both
  # experimental, so we must opt in to the experiment.
  experiments = [module_variable_optional_attrs]
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
  ], var.overrides)

  set {
    name  = "nebari_bot_password"
    value = var.nebari-bot-password
  }

  set {
    name  = "initial_root_password"
    value = var.initial-root-password
  }

  dynamic "set" {
    for_each = var.custom_theme_config != null ? [1] : []
    content {
      name = "extraVolumes"
      value = jsonencode(
        {
          name = "custom-theme"
          persistentVolumeClaim = {
            claimName = "keycloak-git-clone-repo-pvc"
          }
        }
      )
    }
  }

  dynamic "set" {
    for_each = var.custom_theme_config != null ? [1] : []
    content {
      name = "extraVolumesMounts"
      value = jsonencode(
        {
          name      = "custom-theme"
          mountPath = "/opt/jboss/keycloak/themes"
          subPath   = "themes"
        }
      )
    }
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
