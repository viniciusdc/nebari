provider "kubernetes" {

  config_path = "~/.kube/config"


}

module "kubernetes-initialization" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/initialization?ref=dev"

  namespace = var.environment
  secrets   = []
}


module "kubernetes-nfs-server" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/nfs-server?ref=dev"

  name         = "nfs-server"
  namespace    = var.environment
  nfs_capacity = "10Gi"
  node-group   = local.node_groups.general

  depends_on = [
    module.kubernetes-initialization
  ]
}

module "kubernetes-nfs-mount" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/nfs-mount?ref=dev"

  name         = "nfs-mount"
  namespace    = var.environment
  nfs_capacity = "10Gi"
  nfs_endpoint = module.kubernetes-nfs-server.endpoint_ip

  depends_on = [
    module.kubernetes-nfs-server
  ]
}


module "kubernetes-conda-store-server" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/services/conda-store?ref=dev"

  name         = "conda-store"
  namespace    = var.environment
  nfs_capacity = "20Gi"
  node-group   = local.node_groups.general
  environments = {

    "environment-default.yaml" = file("../environments/environment-default.yaml")

  }

  depends_on = [
    module.kubernetes-initialization
  ]
}

module "kubernetes-conda-store-mount" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/nfs-mount?ref=dev"

  name         = "conda-store"
  namespace    = var.environment
  nfs_capacity = "20Gi"
  nfs_endpoint = module.kubernetes-conda-store-server.endpoint_ip

  depends_on = [
    module.kubernetes-conda-store-server
  ]
}

provider "helm" {
  kubernetes {

    config_path = "~/.kube/config"
  }
}

module "kubernetes-ingress" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/ingress?ref=dev"

  namespace = var.environment

  node-group = local.node_groups.general



  depends_on = [
    module.kubernetes-initialization
  ]
}

module "qhub" {
  source = "github.com/quansight/qhub-terraform-modules//modules/kubernetes/services/meta/qhub?ref=dev"

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

