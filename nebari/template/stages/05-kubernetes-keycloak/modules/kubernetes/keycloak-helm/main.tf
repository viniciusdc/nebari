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
  extraInitContainers = var.custom_theme_config != null ? yamlencode([
    local.keycloak_base_jar_container,
    {
      name  = "git-clone"
      image = "bitnami/git:latest"
      volumeMounts = [
        {
          name      = "custom-themes"
          mountPath = "/opt/data/custom-themes"
        },
        {
          name      = "update-git-clone-repo"
          mountPath = "/scripts",
          readOnly  = true
        },
        {
          name      = "keycloak-git-clone-repo-ssh-key"
          mountPath = "/opt/data/keys/.ssh"
        }
      ]
      command = [
        "sh",
        "-c",
        "mkdir -p ~/.ssh && cp /opt/data/keys/.ssh/keycloak-theme-ssh.pem ~/.ssh/keycloak-theme-ssh.pem && chmod 600 ~/.ssh/keycloak-theme-ssh.pem && /scripts/update-git-clone-repo.sh",
        var.custom_theme_config.repository_url,
        "ssh-key-enabled",
      ]
    }
    ]) : yamlencode([
    local.keycloak_base_jar_container
  ])
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
          name = "custom-themes"
          persistentVolumeClaim = {
            claimName = "keycloak-git-clone-repo-pvc"
          }
        },
        {
          name = "keycloak-git-clone-repo-ssh-key"
          secret = {
            secretName  = "keycloak-git-clone-repo-ssh-key"
            defaultMode = 420 # not working. need to fix
          }
        },
        {
          name = "update-git-clone-repo"
          configMap = {
            name = "update-git-clone-repo"
        } },
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
