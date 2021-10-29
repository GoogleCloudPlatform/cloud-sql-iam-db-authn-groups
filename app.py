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
import logging
import google.cloud.logging
from iam_groups_authn.sync import (
    get_credentials,
    get_users_with_roles,
    revoke_iam_group_role,
    grant_iam_group_role,
    UserService,
)
from iam_groups_authn.sql_admin import get_instance_users, add_missing_db_users
from iam_groups_authn.iam_admin import get_iam_users
from iam_groups_authn.mysql import init_connection_engine, RoleService, mysql_username

# define scopes
SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.group.member.readonly",
    "https://www.googleapis.com/auth/sqlservice.admin",
]

app = Quart(__name__)

# start logging client
client = google.cloud.logging.Client()
client.setup_logging()

logging.info("Cloud Run service has started!")


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

    # set ip_type to proper type for connector
    ip_type = IPTypes.PRIVATE if private_ip else IPTypes.PUBLIC

    # grab default creds from cloud run service account
    creds, project = default()
    # update default credentials with IAM and SQL admin scopes
    updated_creds = get_credentials(creds, SCOPES)

    # create UserService object for API calls
    user_service = UserService(creds)

    # keep track of IAM group and database instance tasks
    group_tasks = {}
    instance_tasks = {}

    # loop iam_groups and sql_instances creating async tasks
    for group in iam_groups:
        group_task = asyncio.create_task(get_iam_users(user_service, group))
        group_tasks[group] = group_task

    for instance in sql_instances:
        instance_task = asyncio.create_task(get_instance_users(user_service, instance))
        instance_tasks[instance] = instance_task

    # create pairings of iam groups and instances
    for group in iam_groups:
        for instance in sql_instances:
            # add missing IAM group members to database
            add_users_task = asyncio.create_task(
                add_missing_db_users(
                    user_service, group_tasks[group], instance_tasks[instance], instance
                )
            )

            # initialize database engine
            db = init_connection_engine(instance, updated_creds, ip_type)
            role_service = RoleService(db)

            # verify role for IAM group exists on database, create if does not exist
            role = mysql_username(group)
            verify_role_task = asyncio.create_task(role_service.create_group_role(role))

            # get database users who have group role
            users_with_roles_task = asyncio.create_task(
                get_users_with_roles(role_service, role)
            )

            # await dependent tasks
            results = await asyncio.gather(
                add_users_task, verify_role_task, return_exceptions=True
            )
            # raise exception if found
            for result in results:
                if issubclass(type(result), Exception):
                    raise result

            # log IAM users added as database users
            added_users = results[0]
            if len(added_users) > 0:
                logging.debug(
                    f"[{instance}][{group}] Users added to database: {added_users}"
                )

            # revoke group role from users no longer in IAM group
            revoke_role_task = asyncio.create_task(
                revoke_iam_group_role(
                    role_service,
                    role,
                    users_with_roles_task,
                    group_tasks[group],
                )
            )

            # grant group role to IAM users who are missing it on database
            grant_role_task = asyncio.create_task(
                grant_iam_group_role(
                    role_service,
                    role,
                    users_with_roles_task,
                    group_tasks[group],
                )
            )
            results = await asyncio.gather(
                revoke_role_task, grant_role_task, return_exceptions=True
            )
            # raise exception if found
            for result in results:
                if issubclass(type(result), Exception):
                    raise result

            # log sync info
            revoked_users, granted_users = results
            logging.info(
                f"[{instance}][{group}] Sync successful: {len(revoked_users)} users were revoked group role, {len(granted_users)} users were granted group role."
            )
            logging.debug(f"[{instance}][{group}] Users revoked role: {revoked_users}.")
            logging.debug(f"[{instance}][{group}] Users granted role: {granted_users}.")

    return "Sync successful.", 200
