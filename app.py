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
from iam_groups_authn.sql_admin import (
    get_instance_users,
    add_missing_db_users,
    InstanceConnectionName,
)
from iam_groups_authn.iam_admin import get_iam_users
from iam_groups_authn.utils import DatabaseVersion
from iam_groups_authn.mysql import (
    init_mysql_connection_engine,
    MysqlRoleService,
    mysql_username,
)
from iam_groups_authn.postgres import (
    init_postgres_connection_engine,
    PostgresRoleService,
)

# define scopes
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

    # optional param to change log level
    log_level = body.get("log_level", "INFO")
    if type(log_level) is str and log_level.upper() in log_levels:
        logging.getLogger().setLevel(log_levels[log_level.upper()])

    # set ip_type to proper type for connector
    ip_type = IPTypes.PRIVATE if private_ip else IPTypes.PUBLIC

    # grab default creds from cloud run service account
    creds, project = default()
    # update default credentials with IAM and SQL admin scopes
    updated_creds = get_credentials(creds, SCOPES)

    # create UserService object for API calls
    user_service = UserService(updated_creds)

    # keep track of IAM group and database instance tasks
    group_tasks = {}
    instance_tasks = {}

    # loop iam_groups and sql_instances creating async tasks
    for group in iam_groups:
        group_task = asyncio.create_task(get_iam_users(user_service, group))
        group_tasks[group] = group_task

    for instance in sql_instances:
        instance_task = asyncio.create_task(get_instance_users(user_service, instance))
        database_version_task = asyncio.create_task(
            user_service.get_database_version(
                InstanceConnectionName(*instance.split(":"))
            )
        )
        instance_tasks[instance] = (instance_task, database_version_task)

    # create pairings of iam groups and instances
    for group in iam_groups:
        for instance in sql_instances:

            # get database version of instance and check if supported
            database_version = await instance_tasks[instance][1]
            try:
                database_version = DatabaseVersion(database_version)
            except ValueError as e:
                raise ValueError(
                    f"Unsupported database version for instance `{instance}`. Current supported versions are: {list(DatabaseVersion.__members__.keys())}"
                ) from e

            # add missing IAM group members to database
            add_users_task = asyncio.create_task(
                add_missing_db_users(
                    user_service,
                    group_tasks[group],
                    instance_tasks[instance][0],
                    instance,
                    database_version,
                )
            )

            # initialize database connection pool
            if database_version.is_mysql():
                db = init_mysql_connection_engine(instance, updated_creds, ip_type)
                role_service = MysqlRoleService(db)
            else:
                db = init_postgres_connection_engine(instance, updated_creds, ip_type)
                role_service = PostgresRoleService(db)
            logging.debug(
                "[%s][%s] Initialized a %s connection pool."
                % (instance, group, database_version.value)
            )

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
            logging.debug(
                "[%s][%s] Users added to database: %s."
                % (instance, group, list(added_users))
            )

            # revoke group role from users no longer in IAM group
            revoke_role_task = asyncio.create_task(
                revoke_iam_group_role(
                    role_service,
                    role,
                    users_with_roles_task,
                    group_tasks[group],
                    database_version,
                )
            )

            # grant group role to IAM users who are missing it on database
            grant_role_task = asyncio.create_task(
                grant_iam_group_role(
                    role_service,
                    role,
                    users_with_roles_task,
                    group_tasks[group],
                    database_version,
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
                "[%s][%s] Sync successful: %s users were revoked group role, %s users were granted group role."
                % (instance, group, len(revoked_users), len(granted_users))
            )
            logging.debug(
                "[%s][%s] Users revoked role: %s." % (instance, group, revoked_users)
            )
            logging.debug(
                "[%s][%s] Users granted role: %s." % (instance, group, granted_users)
            )

    return "Sync successful.", 200
