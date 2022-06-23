#! /bin/bash

# Copyright 2022 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# variables required for below commands to properly build and deploy GroupSync
echo "Setting environment variables..."
######################## DEPLOYMENT variables ########################
export PROJECT_ID="" # project ID of project in which you want to deploy the service within
export REGION="" # Google Cloud region to deploy GroupSync in

######################## Service Account variables ########################
export SERVICE_ACCOUNT_NAME="" # name of service account to create and use with GroupSync
export SERVICE_ACCOUNT_EMAIL="$SERVICE_ACCOUNT_NAME@$PROJECT_ID.iam.gserviceaccount.com" # email of service account to deploy Cloud Run with

######################## Cloud Scheduler variables ########################
export PATH_TO_JSON="" # file path to JSON payload containing instance-to-group mappings for Cloud Scheduler
export SCHEDULE="*/10 * * * *" # schedule how often GroupSync Cloud Scheduler is called (defaults to 10 mins)

# load IAM Groups and Cloud SQL Instance names from JSON payload
IAM_GROUPS=$(cat "$PATH_TO_JSON" | jq '.iam_groups' | tr -d '[],"')
SQL_INSTANCES=$(cat "$PATH_TO_JSON" | jq '.sql_instances' | tr -d '[],"')

# check if required variables are set, otherwise give error and exit
declare -a vars=(PROJECT_ID REGION PATH_TO_JSON IAM_GROUPS SQL_INSTANCES)
for var_name in "${vars[@]}"
do
  if [ -z "$(eval "echo \$$var_name")" ]; then
    echo "Missing environment variable $var_name in deployment.sh"
    exit 1
  fi
done

echo "Successfully set environment variables..."

######################## GCP PROJECT CONFIGURATION ########################
echo "Configuring GCP project and region..."
# set project
gcloud config set project "$PROJECT_ID"

# set region
gcloud config set compute/region "$REGION"

echo "Enabling required APIs..."
# enable required APIs within project
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
    cloudbuild.googleapis.com sqladmin.googleapis.com admin.googleapis.com \
    iamcredentials.googleapis.com

######################## SERVICE ACCOUNT CONFIGURATION ########################
echo "Creating Service Account $SERVICE_ACCOUNT_EMAIL..."
# create service account for use with GroupSync (REMOVE STEP IF USING PRE-EXISTING SERVICE ACCOUNT)
gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
  --description="IAM Groups Authn Service Account" \
  --display-name="IAM Database Groups Authentication"

echo "Adding IAM Policies to service account: $SERVICE_ACCOUNT_EMAIL"

# add Cloud Run Invoke Role to service account
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
  --role="roles/run.invoker"

# create custom IAM role and grant to service account
gcloud iam roles create IamAuthnGroups \
  --project="$PROJECT_ID" \
  --title="IAM Groups Authn" \
  --description="Custom role for IAM DB Authn for Groups Service" \
  --permissions=cloudsql.instances.connect,cloudsql.instances.get,cloudsql.instances.login,cloudsql.users.create,cloudsql.users.list,iam.serviceAccounts.signBlob

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
  --role="projects/$PROJECT_ID/roles/IamAuthnGroups"

######################## IAM and DB ROLE CONFIGURATION ########################
echo "Adding Cloud SQL Instance User role to IAM Groups..."
# grant Cloud SQL Instance User role to all IAM group emails (so users of Group can inherit)
for GROUP in $IAM_GROUPS;
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="group:$GROUP" \
    --role="roles/cloudsql.instanceUser"
done

echo "Adding $SERVICE_ACCOUNT_EMAIL as IAM DB User to Cloud SQL Instances..."
# add service account as Cloud SQL IAM User to all mapped instances
for INSTANCE in $SQL_INSTANCES;
do
  IFS=: read -r PROJECT REGION_NAME INSTANCE_NAME <<< $INSTANCE
  gcloud sql users create $SERVICE_ACCOUNT_EMAIL \
    --instance="$INSTANCE_NAME" \
    --type=cloud_iam_service_account
done

############################## CLOUD RUN ################################
echo "Building docker container and deploying GroupSync Cloud Run Service..."
# build container for Cloud Run
gcloud builds submit \
  --tag "gcr.io/$PROJECT_ID/groupsync-run" \
  --project "$PROJECT_ID" \
  --region "$REGION"

# deploy Cloud Run service
gcloud run deploy groupsync-run \
  --image "gcr.io/$PROJECT_ID/groupsync-run" \
  --no-allow-unauthenticated \
  --service-account "$SERVICE_ACCOUNT_EMAIL" \
  --project "$PROJECT_ID" \
  --region "$REGION"

SERVICE_URL=$(gcloud run services describe groupsync-run --platform managed --region "$REGION" --format 'value(status.url)')
echo "Deployed Cloud Run service at URL: $SERVICE_URL"

########################### CLOUD SCHEDULER ############################
echo "Creating GroupSync Cloud Scheduler job..."
# cloud scheduler command (schedules GroupSync to run every 10 minutes)
gcloud scheduler jobs create http groupsync-scheduler \
  --schedule="$SCHEDULE" \
  --uri="$SERVICE_URL/run" \
  --oidc-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --http-method="PUT" \
  --headers="Content-Type=application/json" \
  --message-body-from-file="$PATH_TO_JSON"
