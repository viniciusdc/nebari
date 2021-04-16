provider "kubernetes" {
{% if cookiecutter.provider == "local" %}
  config_path    = "~/.kube/config"
{% else %}
  host                   = module.kubernetes.credentials.endpoint
  token                  = module.kubernetes.credentials.token
  cluster_ca_certificate = module.kubernetes.credentials.cluster_ca_certificate
{% endif %}
}

module "kubernetes-initialization" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/initialization"

  namespace = var.environment
  secrets   = []
}


{% if cookiecutter.provider == "aws" -%}
module "kubernetes-nfs-mount" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/nfs-mount"

  name         = "nfs-mount"
  namespace    = var.environment
  nfs_capacity = "{{ cookiecutter.storage.shared_filesystem }}"
  nfs_endpoint = module.efs.credentials.dns_name

  depends_on = [
    module.kubernetes-nfs-server
  ]
}
{% else -%}
module "kubernetes-nfs-server" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/nfs-server"

  name         = "nfs-server"
  namespace    = var.environment
  nfs_capacity = "{{ cookiecutter.storage.shared_filesystem }}"

  depends_on = [
    module.kubernetes-initialization
  ]
}

module "kubernetes-nfs-mount" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/nfs-mount"

  name         = "nfs-mount"
  namespace    = var.environment
  nfs_capacity = "{{ cookiecutter.storage.shared_filesystem }}"
  nfs_endpoint = module.kubernetes-nfs-server.endpoint_ip

  depends_on = [
    module.kubernetes-nfs-server
  ]
}
{% endif %}

module "kubernetes-conda-store-server" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/services/conda-store"

  name         = "conda-store"
  namespace    = var.environment
  nfs_capacity = "{{ cookiecutter.storage.conda_store }}"
  environments = {
{% for key in cookiecutter.environments %}
    "{{ key }}" = file("../environments/{{ key }}")
{% endfor %}
  }

  depends_on = [
    module.kubernetes-initialization
  ]
}

module "kubernetes-conda-store-mount" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/nfs-mount"

  name         = "conda-store"
  namespace    = var.environment
  nfs_capacity = "{{ cookiecutter.storage.conda_store }}"
  nfs_endpoint = module.kubernetes-conda-store-server.endpoint_ip

  depends_on = [
    module.kubernetes-conda-store-server
  ]
}

provider "helm" {
  kubernetes {
{% if cookiecutter.provider == "local" %}
    config_path = "~/.kube/config"
{% else %}
    load_config_file       = false
    host                   = module.kubernetes.credentials.endpoint
    token                  = module.kubernetes.credentials.token
    cluster_ca_certificate = module.kubernetes.credentials.cluster_ca_certificate
{% endif %}
  }
  version = "1.0.0"
}

{% if cookiecutter.provider == "aws" -%}
module "kubernetes-autoscaling" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/services/cluster-autoscaler"

  namespace = var.environment

  aws-region   = var.region
  cluster-name = local.cluster_name

  depends_on = [
    module.kubernetes-initialization
  ]
}
{% endif -%}

module "kubernetes-ingress" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/ingress"

  namespace = var.environment

  node-group = local.node_groups.general

  depends_on = [
    module.kubernetes-initialization
  ]
}

module "qhub" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/services/meta/qhub"

  name      = "qhub"
  namespace = var.environment

  home-pvc        = module.kubernetes-nfs-mount.persistent_volume_claim.name
  conda-store-pvc = module.kubernetes-conda-store-mount.persistent_volume_claim.name

  external-url = var.endpoint

  jupyterhub-image  = var.jupyterhub-image
  jupyterlab-image  = var.jupyterlab-image
  dask-worker-image = var.dask-worker-image

  general-node-group = local.node_groups.general
  user-node-group    = local.node_groups.user
  worker-node-group  = local.node_groups.worker

  jupyterhub-overrides = [
    file("jupyterhub.yaml")
  ]

  dask-gateway-overrides = [
    file("dask-gateway.yaml")
  ]

  depends_on = [
    module.kubernetes-ingress
  ]
}

{% if cookiecutter.prefect is true -%}
module "prefect" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/services/prefect"

  dependencies = [
    module.qhub.depended_on
  ]
  namespace            = var.environment
  jupyterhub_api_token = module.qhub.jupyterhub_api_token
  prefect_token        = var.prefect_token
}
{% endif -%}
