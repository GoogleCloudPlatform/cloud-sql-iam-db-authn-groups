# Cloud SQL IAM Database Authentication for Groups
**Note:** This is not an officially supported Google product.

A self-deployed service that provides support for managing [Cloud SQL IAM Database Authentication](https://cloud.google.com/sql/docs/mysql/authentication) for groups. This service leverages [Cloud Run](https://cloud.google.com/run), [Cloud Scheduler](https://cloud.google.com/scheduler), and the [Cloud SQL Python Connector](https://github.com/googlecloudplatform/cloud-sql-python-connector) to consistently update and manage Cloud SQL database users based on IAM groups. It automatically creates missing database users and can grant/revoke proper database permissions to all member's of an IAM group at once.

## Supported Databases
Currently only **MySQL 8.0** databases are supported.

## Overview of Service

## Initial Setup for Service
There are a few initial setups steps to get the service ready and grant it the permissions needed in order to successfully operate. However, after this setup is complete, minimal configuration is needed in the future.

### Installation
To run this service successfully, please clone this repository to an environment that thas the Google Cloud SDK installed and initialized. [(Install and initialize the Cloud SDK)](https://cloud.google.com/sdk/docs/install)

```
git clone https://github.com/GoogleCloudPlatform/cloud-sql-iam-db-authn-groups
```
 
Step into the code directory.

```
cd cloud-sql-iam-db-authn-groups
```

Make sure the desired Google Cloud project is set. ([Creating a project](https://cloud.google.com/resource-manager/docs/creating-managing-projects))

```
gcloud config set project PROJECT_ID
```

Replace the following values:
- `PROJECT_ID`: The Google Cloud project ID.

### Enable APIs
This service requires enabling the following Cloud APIs for a successful deployment and lifecycle.
 - [Cloud Run API](https://console.cloud.google.com/apis/api/run.googleapis.com/overview)
 - [Cloud Scheduler API](https://console.cloud.google.com/apis/api/cloudscheduler.googleapis.com/overview)
 - [Cloud Build API](https://console.cloud.google.com/apis/api/cloudbuild.googleapis.com/overview)
 - [Cloud SQL Admin API](https://console.cloud.google.com/apis/api/sqladmin.googleapis.com/overview)
 - [Admin SDK API](https://console.cloud.google.com/apis/api/admin.googleapis.com/overview)
 - [IAM Service Account Credentials API](https://console.cloud.google.com/apis/api/iamcredentials.googleapis.com/overview)

 **Note:** If planning to use service with a Cloud SQL instance that has a Private IP, the following additional APIs need to be enabled. 
 - [Serverless VPC Access API](https://console.cloud.google.com/apis/api/vpcaccess.googleapis.com)
 - [Service Networking API](https://console.cloud.google.com/apis/api/servicenetworking.googleapis.com/overview)

 The above Services and APIs can be manually enabled or enabled all at once by running one of the below commands.

 Enable APIs **without** use of Private IP Cloud SQL instances:

 ```
 gcloud services enable run.googleapis.com cloudscheduler.googleapis.com cloudbuild.googleapis.com sqladmin.googleapis.com admin.googleapis.com iamcredentials.googleapis.com
 ```

 Enable APIs **with** use of Private IP Cloud SQL instances:

 ```
 gcloud services enable run.googleapis.com cloudscheduler.googleapis.com cloudbuild.googleapis.com sqladmin.googleapis.com admin.googleapis.com iamcredentials.googleapis.com vpcaccess.googleapis.com servicenetworking.googleapis.com
 ```

 ### Service Account
A service account must be created and granted the proper IAM roles in order for the service to have appropriate credentials and permissions to access APIs, IAM groups and database users.

The following commands will create a service account and grant it the proper IAM roles for the service to run successfully.

```
gcloud iam service-accounts create SERVICE_ACCOUNT_ID \
    --description="IAM Groups Authn Service Account" \
    --display-name="IAM Database Groups Authentication"
```

Replace the following values:
- `SERVICE_ACCOUNT_ID`: The ID (name) for the service account.

Grant new service account the following IAM roles.

```
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:SERVICE_ACCOUNT_ID@PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/cloudsql.admin"
```

```
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:SERVICE_ACCOUNT_ID@PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountTokenCreator"
```

```
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:SERVICE_ACCOUNT_ID@PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/run.invoker"
```

Replace the following values:
- `SERVICE_ACCOUNT_ID`: The ID (name) for the service account.
- `PROJECT_ID`: The Google Cloud project ID.

### Domain Wide Delegation
To properly allow read-access of an organization's IAM group members (i.e. which IAM users belong within a specific IAM group) within the service, we need to enable [Domain-Wide Delegation](https://developers.google.com/admin-sdk/directory/v1/guides/delegation) for the service account created above. This will allow the service account to properly call the [List Members Discovery API](https://developers.google.com/admin-sdk/directory/reference/rest/v1/members/list) to keep track of the IAM members being managed through this service. Enable Domain-Wide Delegation for the service account created above by following the steps found here, [Enable Domain-Wide Delegation for Service Account](https://developers.google.com/admin-sdk/directory/v1/guides/delegation) starting at "**To enable Google Workspace domain-wide delegation...**" and continue until "**Step 6: Authorize**".

When prompted for OAuth Scopes, give the following scope, **`https://www.googleapis.com/auth/admin.directory.group.member.readonly`** to allow strictly read-only access of IAM group members.

**Note:** An Admin user will be needed for enabling Domain-Wide Delegation for the service account. Keep track of the email address for the admin user who granted the access, it will be needed during a configuration step later on.

### Cloud SQL Instances
This service requires Cloud SQL instances to be already created and to have the `cloudsql_iam_authentication` flag turned **On**. [(How to enable flag)](https://cloud.google.com/sql/docs/mysql/create-edit-iam-instances)

## Deploying Cloud Run Service
To build and deploy the service using Cloud Run, run the following commands.

Build the container image for the service using Cloud Build:

```
gcloud builds submit \
  --tag gcr.io/PROJECT_ID/iam-db-authn-groups \
  --project PROJECT_ID
```

Replace the following values:
- `PROJECT_ID`: The Google Cloud project ID.

Deploy Cloud Run Service from container image:

```
gcloud run deploy iam-db-authn-groups \
  --image gcr.io/PROJECT_ID/iam-db-authn-groups \
  --no-allow-unauthenticated \
  --service-account SERVICE_ACCOUNT_EMAIL \
  --project PROJECT_ID
```

Replace the following values:
- `SERVICE_ACCOUNT_EMAIL`: The email address for the service account.
- `PROJECT_ID`: The Google Cloud project ID.

You should now successfully have a Cloud Run service deployed under the name `iam-db-authn-groups`. The service URL should be outputted from the `gcloud` command above but can also be found in the [Cloud Console](https://console.cloud.google.com/run).

## Configuring Cloud Scheduler
Cloud Scheduler can be used to invoke the Cloud Run service on a timely interval and constantly sync the Cloud SQL instance database users and appropriate database permissions with the given IAM groups. Cloud Scheduler is used to manage and configure multiple mappings between different **Cloud SQL Instances** and **IAM groups** while only needing a single Cloud Run service (for public IP connections).

An example command creating a Cloud Scheduler job to run the IAM database authentication service for IAM groups and Cloud SQL instances can be seen below.

```
gcloud scheduler jobs create http \
    JOB_NAME \
    --schedule="*/10 * * * *" \
    --uri="SERVICE_URL/iam-db-groups" \
    --oidc-service-account-email SERVICE_ACCOUNT_EMAIL \
    --http-method=POST \
    --headers="Content-Type: application/json" \
    --message-body="{"iam-groups": ["group@test.com", "group2@test.com"], "sql_instances": ["project:region:instance", "project:region:instance2], "admin_email": "user@test.com", "private_ip": false}"

```

Replace the following values:
- `JOB_NAME`: The name for the Cloud Scheduler job.
- `SERVICE_URL`: The service URL of the Cloud Run service.
- `SERVICE_ACCOUNT_EMAIL`: The email address for the service account.
- `PROJECT_ID`: The Google Cloud project ID.
- The values for `iam-groups`, `sql_instances`, `admin_email`, and `private_ip`(optional param) within `--message-body`.

The `--schedule` flag is what controls how often the Cloud Scheduler job will trigger the Cloud Run service endpoint. It is currently defaulted to `*/10 * * * *` which will cause it to trigger every 10 minutes. See [Configuring Cron Job Schedules](https://cloud.google.com/scheduler/docs/configuring/cron-job-schedules) on how to format the schedule for different time intervals or [Cron Guru](https://crontab.guru/) to play around with schedule formats.

The body for the POST request to the Cloud Run service can also be configured for Cloud Scheduler through a JSON file by switching out the `--message-body` flag for the flag `--message-body-from-file` where the value is set to the file path of a JSON file with the proper params.

An example JSON config file would look like the following.

```
{
    "iam_groups": ["group@test.com, "group2@test.com],
    "sql_instances": ["project:region:instance"],
    "admin_email": "admin_user@test.com,
    "private_ip": false
}
```

Where:
- **sql_instances**: List of all Cloud SQL instances to configure.
- **iam_groups**: List of all IAM Groups to manage DB users of.
- **admin_email**: Email of user with proper admin privileges for Google Workspace, needed
    for calling Directory API to fetch IAM users within IAM groups.
- **private_ip** (optional): Boolean flag for private or public IP addresses.

**Note:** These are placeholder values and should be replaces with proper IAM groups, Cloud SQL instance connection names, and admin email address.

To learn more about the different Cloud Scheduler flags, read the [official documentation](https://cloud.google.com/sdk/gcloud/reference/scheduler/jobs/create/http).
