variable region {
  type = string
  default = "us-central1"
}


variable project_id {
  type = string
}

variable image {
    type = string
}

variable remove_me_connection_name {
    type = string
}

terraform {
  required_providers {
    google = {
      source = "hashicorp/google"
      version = "3.5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}


resource "google_service_account" "groups_authn" {
  account_id = "groups-authn"
  description = "Service account for the IAM DB groups authn service."
  project    = var.project_id
}

resource "google_project_iam_binding" "cloudsql_client" {
  role    = "roles/cloudsql.client"
  members = [
    "serviceAccount:${google_service_account.groups_authn.email}"
  ]
}


resource "google_cloud_run_service" "groups_authn" {
  name     = "iam db authn groups"
  location = var.region

  template {
    spec {
      service_account_name = google_service_account.groups_authn.email
      containers {
        image = var.image
      }
    }

    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale"      = "1"
        "run.googleapis.com/cloudsql-instances" = var.remove_me_connection_name
        "run.googleapis.com/client-name"        = "terraform"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}
