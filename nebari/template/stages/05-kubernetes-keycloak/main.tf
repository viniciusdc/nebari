terraform {
  # Optional attributes and the defaults function are # both
  # experimental, so we must opt in to the experiment.
  experiments = [module_variable_optional_attrs]
}

resource "random_password" "keycloak-nebari-bot-password" {
  length  = 32
  special = false
}

module "kubernetes-keycloak-helm" {
  source = "./modules/kubernetes/keycloak-helm"

  namespace = var.environment

  external-url = var.endpoint

  nebari-bot-password = random_password.keycloak-nebari-bot-password.result

  initial-root-password = var.initial-root-password

  overrides           = var.overrides
  custom_theme_config = var.keycloak_custom_theme

  node-group = var.node-group
}
