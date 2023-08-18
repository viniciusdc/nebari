variable "name" {
  description = "Prefix name to assign to keycloak kubernetes resources"
  type        = string
}

variable "environment" {
  description = "Kubernetes namespace to deploy keycloak"
  type        = string
}

variable "endpoint" {
  description = "nebari cluster endpoint"
  type        = string
}

variable "initial-root-password" {
  description = "Keycloak root user password"
  type        = string
}

variable "overrides" {
  # https://github.com/codecentric/helm-charts/blob/master/charts/keycloak/values.yaml
  description = "Keycloak helm chart overrides"
  type        = list(string)
  default     = []
}

variable "node-group" {
  description = "Node key value pair for bound general resources"
  type = object({
    key   = string
    value = string
  })
}


variable "keycloak_custom_theme" {
  description = "Keycloak custom theme configuration"
  type = object({
    custom_theme         = optional(object({
      repository_url = string
      ssh_key        = optional(string)
    }))
  })
}
