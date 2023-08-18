resource "random_password" "keycloak-nebari-bot-password" {
  length  = 32
  special = false
}

resource "kubernetes_config_map" "keycloak-custom-themes" {
  metadata {
    name      = "keycloak-custom-themes"
    namespace = var.namespace
  }

  data = {
    for filename in fileset("${var.custom_themes_path}", "*") :
    filename => file("${var.custom_themes_path}/${filename}")
  }
}

module "kubernetes-keycloak-helm" {
  experiments = [module_variable_optional_attrs]

  source = "./modules/kubernetes/keycloak-helm"

  namespace = var.environment

  external-url = var.endpoint

  nebari-bot-password = random_password.keycloak-nebari-bot-password.result

  initial-root-password = var.initial-root-password

  overrides = var.overrides
  custom_theme_config = var.keycloak_custom_theme

  node-group = var.node-group
}
