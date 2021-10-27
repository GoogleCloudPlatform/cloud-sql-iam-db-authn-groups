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

import asyncio
from quart import Quart, request
from google.auth import default
from google.cloud.sql.connector.instance_connection_manager import IPTypes
from iam_groups_authn.sync import (
    get_credentials,
    get_users_to_add,
    manage_instance_users,
    UserService,
)
from iam_groups_authn.sql_admin import get_instance_users, InstanceConnectionName
from iam_groups_authn.iam_admin import get_iam_users

# define scopes
SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
    "https://www.googleapis.com/auth/sqlservice.admin",
]

app = Quart(__name__)


@app.route("/", methods=["GET"])
def health_check():
    return "App is running!"


@app.route("/run", methods=["PUT"])
async def run_groups_authn():
    body = await request.get_json(force=True)
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

    # try reading in private_ip param, default to False
    private_ip = body.get("private_ip", False)
    if type(private_ip) is not bool:
        return (
            "Incorrect type for request parameter: `private_ip`, should be boolean.",
            400,
        )

    # grab default creds from cloud run service account
    creds, project = default()
    # update default credentials with IAM and SQL admin scopes
    updated_creds = get_credentials(creds, SCOPES)

    # create UserService object for API calls
    user_service = UserService(creds)

    iam_users, instance_users = await asyncio.gather(
        get_iam_users(user_service, iam_groups),
        get_instance_users(user_service, sql_instances),
    )

    # get IAM users of each IAM group
    for group_name, user_list in iam_users.items():
        print(f"IAM Users in Group {group_name}: {user_list}")

    # get all instance DB users
    for instance_name, db_users in instance_users.items():
        print(f"DB Users in instance `{instance_name}`: {db_users}")

    # find IAM users who are missing as DB users
    users_to_add = get_users_to_add(iam_users, instance_users)
    for instance, users in users_to_add.items():
        print(f"Missing IAM DB users for instance `{instance}`: {users}")
        for user in users:
            user_service.insert_db_user(
                user, InstanceConnectionName(*instance.split(":"))
            )

    # set ip_type to proper type for connector
    ip_type = IPTypes.PRIVATE if private_ip else IPTypes.PUBLIC

    # for each instance manage users and group role permissions
    instance_coroutines = [
        manage_instance_users(instance, iam_users, updated_creds, ip_type)
        for instance in sql_instances
    ]
    await asyncio.gather(*instance_coroutines)

    return "Sync successful.", 200
