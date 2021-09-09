#! /bin/bash

export CLOUD_SQL_CONNECTION_NAME=
export PROJECT_ID=

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
