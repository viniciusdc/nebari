variable "name" {
  type    = string
  default = "thisisatest"
}

variable "environment" {
  type    = string
  default = "dev"
}

# jupyterhub
variable "endpoint" {
  description = "Jupyterhub endpoint"
  type        = string
  default     = "github-actions.qhub.dev"
}

variable "jupyterhub-image" {
  description = "Jupyterhub user image"
  type = object({
    name = string
    tag  = string
  })
  default = {
    name = "quansight/qhub-jupyterhub"
    tag  = "d52cea07f70cc8b35c29b327bbd2682f29d576ad"
  }
}

variable "jupyterlab-image" {
  description = "Jupyterlab user image"
  type = object({
    name = string
    tag  = string
  })
  default = {
    name = "sha256"
    tag  = "8674f4d90cb76abe40ea5d871339b58582991acca000975983a7fe603ea354e2"
  }
}

variable "dask-worker-image" {
  description = "Dask worker image"
  type = object({
    name = string
    tag  = string
  })
  default = {
    name = "quansight/qhub-dask-worker"
    tag  = "d52cea07f70cc8b35c29b327bbd2682f29d576ad"
  }
}


