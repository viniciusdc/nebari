terraform {
  # Optional attributes and the defaults function are # both
  # experimental, so we must opt in to the experiment.
  experiments = [module_variable_optional_attrs]
}

locals {
  keycloak_base_jar_container = {
    name  = "keycloak-base-jar"
    image = "busybox:1.31"
    command = [
      "sh",
      "-c",
      "mkdir -p /opt/jboss/keycloak/providers/ && cp /opt/keycloak/providers/keycloak-metrics-spi-2.5.3.jar /opt/jboss/keycloak/providers/keycloak-metrics-spi-2.5.3.jar && chown 1000:1000 /opt/jboss/keycloak/providers/keycloak-metrics-spi-2.5.3.jar && chmod 777 /opt/jboss/keycloak/providers/keycloak-metrics-spi-2.5.3.jar",
    ]
    securityContext = {
      runAsUser = 0
    }
    volumeMounts = [
      {
        name      = "metrics-plugin"
        mountPath = "/opt/keycloak/providers/"
      }
    ]
  }
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
      # Custom theme configuration for keycloak
      startupScripts = {
        "mv-custom-themes.sh" = file("${path.module}/files/mv-custom-themes.sh")
      }

      extraInitContainers = local.extraInitContainers

      extraVolumes = yamlencode([
        {
          name     = "custom-themes"
          emptyDir = {}
        },
        {
          name = "keycloak-git-sync-ssh-key"
          secret = {
            defaultMode = 256
            secretName  = "keycloak-git-sync-ssh-key"
          }
        },
        {
          name = "metrics-plugin"
          secret = {
            secretName = "keycloak-metrics-plugin"
          }
        }
      ])
      extraVolumeMounts = yamlencode([
        {
          name      = "custom-themes"
          mountPath = "/opt/data/themes/"
          subPath   = "themes"
        },
        {
          name      = "metrics-plugin"
          mountPath = "/opt/jboss/keycloak/providers/"
        }
      ])
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
