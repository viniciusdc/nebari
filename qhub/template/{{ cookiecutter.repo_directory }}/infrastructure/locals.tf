locals {
  additional_tags = {
    Project     = var.name
    Owner       = "terraform"
    Environment = var.environment
  }

  cluster_name = "${var.name}-${var.environment}"

  node_groups = {
    general = {
{%- if cookiecutter.provider == "aws" %}
      key   = "eks.amazonaws.com/nodegroup"
      value = "general"
{%- elif cookiecutter.provider == "gcp" %}
      key   = "cloud.google.com/gke-nodepool"
      value = "general"
{%- elif cookiecutter.provider == "do" %}
      key   = "doks.digitalocean.com/node-pool"
      value = "general"
{%- else %}
      key   = "kubernetes.io/os"
      value = "linux"
{% endif %}
    }

    user = {
{%- if cookiecutter.provider == "aws" %}
      key   = "eks.amazonaws.com/nodegroup"
      value = "user"
{%- elif cookiecutter.provider == "gcp" %}
      key   = "cloud.google.com/gke-nodepool"
      value = "user"
{%- elif cookiecutter.provider == "do" %}
      key   = "doks.digitalocean.com/node-pool"
      value = "user"
{%- else %}
      key   = "kubernetes.io/os"
      value = "linux"
{% endif %}
    }

    worker = {
{%- if cookiecutter.provider == "aws" %}
      key   = "eks.amazonaws.com/nodegroup"
      value = "worker"
{%- elif cookiecutter.provider == "gcp" %}
      key   = "cloud.google.com/gke-nodepool"
      value = "worker"
{%- elif cookiecutter.provider == "do" %}
      key   = "doks.digitalocean.com/node-pool"
      value = "worker"
{%- else %}
      key   = "kubernetes.io/os"
      value = "linux"
{% endif %}
    }
  }
}
