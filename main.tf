variable region {
  type = string
  default = "us-central1"
}

variable zone {
  type = string
  default = "us-centra11-c"
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
      version = "3.87.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

resource "google_service_account" "groups_authn" {
  account_id  = "groups-authn"
  description = "Service account for the IAM DB groups authn service."
  project     = var.project_id
}

resource "google_service_account" "scheduler" {
  account_id = "scheduler"
  description = "Service account for Cloud scheduler"
  project    = var.project_id
}

resource "google_project_iam_binding" "cloudsql_client" {
  role    = "roles/cloudsql.client"
  members = [
    "serviceAccount:${google_service_account.groups_authn.email}"
  ]
}

resource "google_project_iam_binding" "token_creator_iam" {
  role    = "roles/iam.serviceAccountTokenCreator"
  members = [
    "serviceAccount:${google_service_account.groups_authn.email}"
  ]
}

resource "google_project_iam_binding" "run_invoker" {
  role    = "roles/run.invoker"
  members = [
    "serviceAccount:${google_service_account.groups_authn.email}",
    "serviceAccount:${google_service_account.scheduler.email}",
  ]
}

# Enables the Cloud Run API
resource "google_project_service" "run_api" {
  service = "run.googleapis.com"

  disable_on_destroy = true
}

resource "google_cloud_run_service" "groups_authn_service" {
  name     = "iam-db-authn-groups"
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
  
  depends_on = [google_project_service.run_api]
}

# Display the service URL
output "service_url" {
  value = google_cloud_run_service.groups_authn_service.status[0].url
}

data "google_iam_policy" "noauth" {
  binding {
    role = "roles/run.invoker"
    members = [
      "allUsers",
    ]
  }
}

resource "google_cloud_run_service_iam_policy" "noauth" {
  location    = google_cloud_run_service.groups_authn_service.location
  project     = var.project_id
  service     = google_cloud_run_service.groups_authn_service.name

  policy_data = data.google_iam_policy.noauth.policy_data
}

resource "google_cloud_scheduler_job" "group_authn_scheduler" {
  name             = "IAM-groups-authn-scheduler"
  description      = "Job to trigger IAM groups authn"
  schedule         = "*/10 * * * *"
  time_zone        = "GMT" 

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "GET"
    uri         = "${google_cloud_run_service.groups_authn_service.status[0].url}/"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
    }
  }
}
