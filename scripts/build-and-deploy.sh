#! /bin/bash

# Copyright 2021 Google LLC
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

# variables required for below commands to properly build and deploy Cloud Run
export PROJECT_ID= # project ID of project in which you want to deploy the service within
export SERVICE_ACCOUNT_EMAIL= # email of service account to deploy Cloud Run with

# check if variables are set, otherwise give error and exit
declare -a vars=(PROJECT_ID SERVICE_ACCOUNT_EMAIL)
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

gcloud run deploy iam-db-authn-groups \
  --image gcr.io/$PROJECT_ID/iam-db-authn-groups \
  --no-allow-unauthenticated \
  --service-account $SERVICE_ACCOUNT_EMAIL \
  --project $PROJECT_ID
