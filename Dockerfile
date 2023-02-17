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

# use python image
FROM python:3.11

# Allow statements and log messages to immediately appear in Knative logs
ENV PYTHONUNBUFFERED True

# copy local code to container image
ENV APP_HOME /app
WORKDIR $APP_HOME
COPY . ./

# Install production dependencies
RUN pip install -r requirements.txt

# Run the web service on container startup. Here we use the hypercorn
# webserver, with one worker process.
# For environments with multiple CPU cores, increase the number of workers
# to be equal to the cores available
CMD exec hypercorn --bind :$PORT --workers 1 app:app
