#! /bin/bash

# variables required for below commands to properly build and deploy Cloud Run
export CLOUD_SQL_CONNECTION_NAME= # i.e "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>"
export PROJECT_ID= # project ID of project in which you want to deploy the service within

gcloud builds submit \
  --tag gcr.io/$PROJECT_ID/iam-db-authn-groups \
  --project $PROJECT_ID

gcloud beta run deploy iam-db-authn-groups \
  --image gcr.io/$PROJECT_ID/iam-db-authn-groups \
  --allow-unauthenticated \
  --add-cloudsql-instances $CLOUD_SQL_CONNECTION_NAME \
  --update-secrets=DB_USER=DB_USER:latest \
  --update-secrets=DB_PASS=DB_PASS:latest \
  --update-secrets=DB_NAME=DB_NAME:latest \
  --update-secrets=CLOUD_SQL_CONNECTION_NAME=CLOUD_SQL_CONNECTION_NAME:latest \
  --project $PROJECT_ID
