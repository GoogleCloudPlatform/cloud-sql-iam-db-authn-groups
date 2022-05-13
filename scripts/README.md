# GroupSync: Cloud SQL IAM Database Authentication for Groups
**Note:** This project is experimental and is not an officially supported Google product.

GroupSync is a self-deployed service that provides support for managing [Cloud SQL IAM Database Authentication](https://cloud.google.com/sql/docs/mysql/authentication) for groups. GroupSync leverages [Cloud Run](https://cloud.google.com/run), [Cloud Scheduler](https://cloud.google.com/scheduler), and the [Cloud SQL Python Connector](https://github.com/googlecloudplatform/cloud-sql-python-connector) to consistently update and sync Cloud SQL instances based on IAM groups. It will create missing database IAM users, GRANT roles to database IAM users based on their IAM groups, and REVOKE roles from database IAM users no longer in IAM groups.

## Build and Deploy GroupSync Using a Script
Below outlines the steps to automate the majority of a GroupSync deployment, allowing for faster and more scalable deployments.
This deployment uses a script to build the appropriate GroupSync resources:
- Service Account with required permissions
- Serverless VPC Access Connector
- Cloud Run service
- Cloud Scheduler Job

### Setup
To run this service successfully, please clone this repository to an environment that has the Google Cloud SDK installed and initialized. [(Install and initialize the Cloud SDK)](https://cloud.google.com/sdk/docs/install)

```
git clone https://github.com/GoogleCloudPlatform/cloud-sql-iam-db-authn-groups
```

Step into the code directory.

```
cd cloud-sql-iam-db-authn-groups
```

### Create a JSON File
Each Cloud Scheduler Job requires a JSON payload to tell it which IAM Groups and
Cloud SQL instances to sync, and an optional flag to toggle between public or
private IP database connections (defaults to public IP).

Create a **.json** file that will be used to configure a GroupSync Cloud
Scheduler Job between the desired IAM Groups and Cloud SQL Instances. 

```json
{
    "iam_groups": ["group@test.com", "group2@test.com"],
    "sql_instances": ["project:region:instance"],
    "private_ip": true
}
```

### Set Required Variables within Deployment Script
The script used to facilitate the deployment of GroupSync is
[build-and-deploy-private-ip.sh](build-and-deploy-private-ip.sh).

Edit the following variables at the top of the script with the
proper values for your deployment.
```bash
export PROJECT_ID="" # project ID of project in which you want to deploy the service within
export REGION="" # Google Cloud region to deploy GroupSync in

export SERVICE_ACCOUNT_NAME="" # name of service account to create and use with GroupSync
export SERVICE_ACCOUNT_EMAIL="$SERVICE_ACCOUNT_NAME@$PROJECT_ID.iam.gserviceaccount.com" # email of service account to deploy Cloud Run with

export HOST_PROJECT_ID="" # project ID of Shared VPC host project (optional)
export CONNECTOR_NAME="" # name to be given to Serverless VPC Access Connector
export SUBNET="" # the name of an unused /28 subnet for Serverless VPC Access Connector

export PATH_TO_JSON="" # relative file path to JSON file containing instance-to-group mappings for Cloud Scheduler
export SCHEDULE="*/10 * * * *" # schedule how often GroupSync Cloud Scheduler is called (defaults to 10 mins)
```

### Run Script
Now the deployment script can be run by executing the following command:

```bash
./scripts/build-and-deploy-private-ip.sh
```

**NOTE:** Some commands may fail without the GroupSync deployment all-together failing.
(ex. `gcloud iam service-accounts create` may fail if your service acount
already exists but the following command will then use the pre-existing service account)

Once the script is finished running, the Cloud Run and Cloud Scheduler services will be deployed.
However, the first Cloud Scheduler job will fail as a few more permissions are required.


## Manual Steps
The following steps are required for the Cloud Scheduler job to begin successfully running
and are not currently able to be automated within the deployment script.

### Assign Group Administrator Role to Service Account
To properly allow read-access of an organization's IAM group members
(i.e. which IAM users belong within a specific IAM group) within the
GroupSync service, we need to assign the Google Workspace Group Administrator
Role to the service account that was created by the deployment script.
This will allow the service account to properly call the
[List Members Discovery API](https://developers.google.com/admin-sdk/directory/reference/rest/v1/members/list)
to keep track of the IAM members being managed through this service.

Your service account email will be following `<SERVICE_ACCOUNT_NAME>@<PROJECT_ID>.iam.gserviceaccount.com`

To assign the Group Administator Role to the service account follow these four quick steps.
([How to Assign Group Administrator Role](https://cloud.google.com/identity/docs/how-to/setup#auth-no-dwd))

### Granting Database Permissions to the Service Account's Database User
For GroupSync to run smoothly it needs an IAM service account database user with
permissions on all Cloud SQL instances defined within the JSON file.
This allows for the GroupSync service to read the names of database users
and GRANT/REVOKE group role(s) appropriately.

Connect to all Cloud SQL instances defined within the JSON file
as an admin user or another database user with appropriate permissions for the following commands.
([Connecting to an Instance](https://cloud.google.com/sql/docs/mysql/connect-overview))

Once connected, grant the service account IAM database user that was created by the
deployment script the following permissions:

#### MySQL Instance
Replace the following values in the below commands:
- `SERVICE_ACCOUNT_NAME`: The name of the service account (everything before the **@** portion of email)
Allow the service account to read database users and their roles.

```sql
GRANT SELECT ON mysql.role_edges TO '<SERVICE_ACCOUNT_NAME>';
```

Allow the service account to **CREATE** group roles for IAM groups if they are missing.

```sql
GRANT CREATE ROLE ON *.* TO '<SERVICE_ACCOUNT_NAME>';
```

Allow the service account to **GRANT/REVOKE** roles to users through being a **ROLE_ADMIN**.

```sql
GRANT ROLE_ADMIN ON *.* TO '<SERVICE_ACCOUNT_NAME>';
```

#### PostgreSQL Instance
Postgres allows a role or user to easily be granted the appropriate permissions for
**CREATE**, and **GRANT/REVOKE** that are needed for creating and managing the group
roles for IAM groups with one single command.

Replace the following values:
- `SERVICE_ACCOUNT_EMAIL`: The email address for the service account with the `.gserviceaccount.com` suffix removed.

```sql
ALTER ROLE "<SERVICE_ACCOUNT_EMAIL>" WITH CREATEROLE;
```

## Successful Cloud Scheduler Job
After the previous permissions have been granted, the next Cloud
Scheduler job to be triggered and all following ones should run successfully.

All IAM users belonging to the configured IAM Groups should now be synced as DB
users across all mapped Cloud SQL Instances.

**REMINDER:** Appropriate database permissions must still be granted to each of
the database roles on the Cloud SQL Instances associated with a given IAM group.
