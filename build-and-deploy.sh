#! /bin/bash

# variables required for below commands to properly build and deploy Cloud Run
export CLOUD_SQL_CONNECTION_NAME= # i.e "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>"
export PROJECT_ID= # project ID of project in which you want to deploy the service within
export SERVICE_ACCOUNT= # email of service account to deploy Cloud Run with

# check if variables are set, otherwise give error and exit
declare -a vars=(CLOUD_SQL_CONNECTION_NAME PROJECT_ID SERVICE_ACCOUNT)
for var_name in "${vars[@]}"
do
  if [ -z "$(eval "echo \$$var_name")" ]; then
    echo "Missing environment variable $var_name in build-and-deploy.sh"
    exit 1
  fi
done

gcloud builds submit \
  --tag gcr.io/$PROJECT_ID/iam-db-authn-groups \
  --project $PROJECT_ID

gcloud beta run deploy iam-db-authn-groups \
  --image gcr.io/$PROJECT_ID/iam-db-authn-groups \
  --allow-unauthenticated \
  --service-account $SERVICE_ACCOUNT \
  --project $PROJECT_ID
