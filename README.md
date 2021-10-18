# Cloud SQL IAM Database Authentication for Groups
**Note:** This is not an officially supported Google product.

A self-deployed service that provides support for managing [Cloud SQL IAM Database Authentication](https://cloud.google.com/sql/docs/mysql/authentication) for groups. This service leverages [Cloud Run](https://cloud.google.com/run), [Cloud Scheduler](https://cloud.google.com/scheduler), and the [Cloud SQL Python Connector](https://github.com/googlecloudplatform/cloud-sql-python-connector) to consistently update and manage Cloud SQL database users based on IAM groups. It automatically creates missing database users and can grant/revoke proper database permissions to all member's of an IAM group at once.

# Supported Databases
Currently only **MySQL 8.0** databases are supported.

## Overview of Service

## Initial Setup for Service
There are a few initial setups steps to get the service ready and grant it the permissions needed in order to successfully operate. However, after this setup is complete, minimal configuration is needed in the future.

### Installation
To run this service successfully, please clone this repository to an environment that thas the Google Cloud SDK installed [installation instructions](https://cloud.google.com/sdk/docs/install).

```
git clone https://github.com/GoogleCloudPlatform/cloud-sql-iam-db-authn-groups
```

### Enable APIs
This service requires enabling the following Cloud APIs for a successful deployment and lifecycle.
 - [Cloud Run Admin API](https://console.cloud.google.com/apis/api/run.googleapis.com/overview)
 - [Cloud Scheduler API](https://console.cloud.google.com/apis/api/cloudscheduler.googleapis.com/overview)
 - [Cloud SQL Admin API](https://console.cloud.google.com/apis/api/sqladmin.googleapis.com/overview)
 - [Admin SDK API](https://console.cloud.google.com/apis/api/admin.googleapis.com/overview)
 - [IAM Service Account Credentials API](https://console.cloud.google.com/apis/api/iamcredentials.googleapis.com/overview)

 **Note:** If planning to use service with a Cloud SQL instance that has a Private IP, the following additional APIs need to be enabled. 
 - [Serverless VPC Access API](https://console.cloud.google.com/apis/api/vpcaccess.googleapis.com)
 - [Service Networking API](https://console.cloud.google.com/apis/api/servicenetworking.googleapis.com/overview)

 The above Services and APIs can be manually enabled or enabled all at once by running one of the below commands.

 Enable APIs **without** use of Private IP Cloud SQL instances:

 ```
 gcloud services enable run.googleapis.com cloudscheduler.googleapis.com sqladmin.googleapis.com admin.googleapis.com iamcredentials.googleapis.com
 ```

 Enable APIs **with** use of Private IP Cloud SQL instances:

 ```
 gcloud services enable run.googleapis.com cloudscheduler.googleapis.com sqladmin.googleapis.com admin.googleapis.com iamcredentials.googleapis.com vpcaccess.googleapis.com servicenetworking.googleapis.com
 ```

 ### Service Account
A service account must be created and granted the proper IAM roles in order for the service to have appropriate credentials and permissions to access APIs, IAM groups and database users.

The following commands will create a service account and grant it the proper IAM roles for the service to run successfully.

```
gcloud iam service-accounts create SERVICE_ACCOUNT_ID \
    --description="IAM Groups Authn Service Account" \
    -- display-name="IAM Database Groups Authentication"
```

Replace the following values:
- `SERVICE_ACCOUNT_ID`: The ID (name) for the service account.

Grant new service account the following IAM roles.

```
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:SERVICE_ACCOUNT_ID@PROJECT_ID.iam.gserviceaccount.com"
    --role="roles/cloudsql.admin"
```

```
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:SERVICE_ACCOUNT_ID@PROJECT_ID.iam.gserviceaccount.com"
    --role="roles/iam.serviceAccountTokenCreator"
```

```
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:SERVICE_ACCOUNT_ID@PROJECT_ID.iam.gserviceaccount.com"
    --role="roles/run.invoker"
```

Replace the following values:
- `SERVICE_ACCOUNT_ID`: The ID (name) for the service account.
- `PROJECT_ID`: The project ID (name).

### Domain Wide Delegation

### Cloud SQL Instances
This service requires Cloud SQL instances to be already created and to have the `cloudsql_iam_authentication` flag turned **On**. [See HERE for help](https://cloud.google.com/sql/docs/mysql/create-edit-iam-instances)

## Deploying Cloud Run Service

## Configuring Cloud Scheduler
