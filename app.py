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

from quart import Quart
import quart
from google.auth import default
from google.auth.transport.requests import Request
import logging
import google.cloud.logging
from iam_groups_authn.sync import GroupRoleMaxLengthError, groups_sync

# define OAuth2 scopes
SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
    "https://www.googleapis.com/auth/sqlservice.admin",
]

app = Quart(__name__)

# start logging client
client = google.cloud.logging.Client()
client.setup_logging()
log_levels = {
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

# grab default creds from cloud run service account
creds, project = default(scopes=SCOPES)


@app.route("/", methods=["GET"])
def health_check():
    return "App is running!"


@app.route("/run", methods=["PUT"])
async def run_groups_authn():
    body = await quart.request.get_json(force=True)
    # try reading in required request parameters and verify type, otherwise throw custom error
    sql_instances = body.get("sql_instances")
    if sql_instances is None or type(sql_instances) is not list:
        return (
            "Missing or incorrect type for required request parameter: `sql_instances`",
            400,
        )

    iam_groups = body.get("iam_groups")
    if iam_groups is None or type(iam_groups) is not list:
        return (
            "Missing or incorrect type for required request parameter: `iam_groups`",
            400,
        )

    group_roles = body.get("group_roles", dict())
    if type(group_roles) is not dict:
        return (
            "Incorrect type for request parameter: `group_roles`, should be dict/JSON",
            400,
        )     

    # try reading in private_ip param, default to False
    private_ip = body.get("private_ip", False)
    if type(private_ip) is not bool:
        return (
            "Incorrect type for request parameter: `private_ip`, should be boolean.",
            400,
        )

    # optional param to change log level
    log_level = body.get("log_level", "INFO")
    if type(log_level) is str and log_level.upper() in log_levels:
        logging.getLogger().setLevel(log_levels[log_level.upper()])

    # check if credentials are expired
    if not creds.valid:
        request = Request()
        creds.refresh(request)

    try:
        # sync IAM groups to Cloud SQL instances
        await groups_sync(iam_groups, sql_instances, creds, group_roles, private_ip)
    except GroupRoleMaxLengthError as e:
        logging.exception(f"Error during sync: {str(e)}")
        return (
            str(e),
            400,
        )
    return "Sync successful.", 200
