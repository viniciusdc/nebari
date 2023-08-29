terraform {
  # Optional attributes and the defaults function are # both
  # experimental, so we must opt in to the experiment.
  experiments = [module_variable_optional_attrs]
}


locals {
  sshKeyVolumeConfig = var.custom_theme_config != null ? {
    name = "ssh-secret"
    secret = {
      secretName = "keycloak-git-ssh-secret"
    }
  } : {}
  extraInitContainersTheming = var.custom_theme_config != null ? yamlencode([
    {
      name  = "git-clone"
      image = "bitnami/git:latest"
      volumeMounts = [
        {
          name      = "custom-themes"
          mountPath = "/opt/data/custom-themes"
        },
        {
          name      = "ssh-secret"
          mountPath = "/root/.ssh"
          readOnly  = true
        }
      ]
      command = [
        "sh",
        "-c",
        "if [ ! -d /opt/data/custom-themes/themes/.git ]; then cd /opt/data/custom-themes && git clone ${var.custom_theme_config.repository_url} themes; else cd /opt/data/custom-themes && git -C /opt/data/custom-themes/themes pull; fi"
      ]
    }
  ]) : ""
  #   {
  #     name  = "git-clone"
  #     image = "bitnami/git:latest"
  #     volumeMounts = [
  #       {
  #         name      = "custom-themes"
  #         mountPath = "/opt/data/custom-themes"
  #       }
  #     ]
  #     command = [
  #       "sh",
  #       "-c",
  #       "if [ ! -d /opt/data/custom-themes/themes/.git ]; then cd /opt/data/custom-themes && git clone ${var.custom_theme_config.repository_url} themes; else cd /opt/data/custom-themes && git -C /opt/data/custom-themes/themes pull; fi"
  #     ]
  #   }
  # ] : []
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
      extraInitContainers = local.extraInitContainersTheming
      extraVolumes = yamlencode([
        {
          name = "custom-themes"
          persistentVolumeClaim = {
            claimName = "keycloak-git-clone-repo-pvc"
          }
        },
        local.sshKeyVolumeConfig
      ])
      extraVolumeMounts = yamlencode([
        {
          name      = "custom-themes"
          mountPath = "/opt/data/themes/"
          subPath   = "themes"
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
