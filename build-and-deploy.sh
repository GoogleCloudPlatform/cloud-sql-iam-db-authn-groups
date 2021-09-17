#! /bin/bash

# variables required for below commands to properly build and deploy Cloud Run
export CLOUD_SQL_CONNECTION_NAME= # i.e "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>"
export PROJECT_ID= # project ID of project in which you want to deploy the service within
export SERVICE_ACCOUNT= # email of service account to deploy Cloud Run with

gcloud builds submit \
  --tag gcr.io/$PROJECT_ID/iam-db-authn-groups \
  --project $PROJECT_ID

gcloud beta run deploy iam-db-authn-groups \
  --image gcr.io/$PROJECT_ID/iam-db-authn-groups \
  --allow-unauthenticated \
  --service-account $SERVICE_ACCOUNT \
  --project $PROJECT_ID
