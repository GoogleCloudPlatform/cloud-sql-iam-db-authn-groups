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

# sync.py contains functions for syncing IAM groups with Cloud SQL instances

import asyncio
from google.auth.transport.requests import Request
from google.cloud.sql.connector.instance_connection_manager import IPTypes
import json
from aiohttp import ClientSession
from enum import Enum
from typing import Any, Optional
import logging
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


async def groups_sync(
    iam_groups, sql_instances, credentials, group_roles, private_ip=False
):
    """GroupSync method to sync IAM groups with Cloud SQL instances.

    Args:
        iam_groups: List of iam group emails for IAM groups to sync.
            (e.g. ["iam-group@test.com", "iam-group2@test.com"])
        sql_instances: List of instance connection names for Cloud SQL instances to sync.
            (e.g. ["<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>"])
        credentials: OAuth2 credentials.
        group_roles:(optional) Dict of IAM group emails as keys and group database
            role names as values. The group database role name is the database role
            that will be granted/revoked within GroupSync to each member of the
            corresponding IAM group. Group role names default to IAM group email
            without the domain (everything before the @, i.e "iam-group@test.com"
            would have group role name of "iam-group".
            (e.g.
                {
                    "iam-group@test.com": "engineering",
                    "iam-group2@test.com": "accounting"
                }
            )
        private_ip:(optional) Boolean flag for connecting to Cloud SQL databases with
            Private or Public IPs. (defaults to False for Public IP)
    """
    # set ip_type to proper type for connector
    ip_type = IPTypes.PRIVATE if private_ip else IPTypes.PUBLIC

    # create aiohttp client session for async API calls
    client_session = ClientSession(headers={"Content-Type": "application/json"})

    # create UserService object for API calls
    user_service = UserService(client_session, credentials)

    # keep track of IAM group and database instance tasks
    group_tasks = {}
    instance_tasks = {}

    # loop iam_groups and sql_instances creating async tasks
    for group in iam_groups:
        group_task = asyncio.create_task(get_iam_users(user_service, group))
        group_tasks[group] = group_task

    for instance in sql_instances:
        instance_task = asyncio.create_task(get_instance_users(user_service, instance))
        database_version = await user_service.get_database_version(
            InstanceConnectionName(*instance.split(":"))
        )
        # verify that group role for database won't exceed character limit
        verify_group_role_length(iam_groups, group_roles, database_version)
        instance_tasks[instance] = (instance_task, database_version)

    # create pairings of iam groups and instances
    for group in iam_groups:
        for instance in sql_instances:
            database_version = instance_tasks[instance][1]
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
                db = init_mysql_connection_engine(instance, credentials, ip_type)
                role_service = MysqlRoleService(db)
            else:
                db = init_postgres_connection_engine(instance, credentials, ip_type)
                role_service = PostgresRoleService(db)
            logging.debug(
                "[%s][%s] Initialized a %s connection pool."
                % (instance, group, database_version.value)
            )

            # verify role for IAM group exists on database, create if does not exist
            role = group_roles.get(group, mysql_username(group))
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

    # close aiohttp client session for graceful exit
    if not client_session.closed:
        await client_session.close()


class UserService:
    """Helper class for building googleapis service calls."""

    def __init__(self, client_session, creds):
        """Initialize UserService instance.

        Args:
            client_session: aiohttp client session object for API calls.
            creds: OAuth2 credentials to call admin APIs.
        """
        self.client_session = client_session
        self.creds = creds

    async def get_group_members(self, group):
        """Get all members of an IAM group.

        Given an IAM group, get all members (groups or users) that belong to the
        group.

        Args:
            group (str): A single IAM group identifier key (name, email, ID).

        Returns:
            members: List of all members (groups or users) that belong to the IAM group.
        """
        # build service to call Admin SDK Directory API
        url = f"https://admin.googleapis.com/admin/directory/v1/groups/{group}/members"

        try:
            # call the Admin SDK Directory API
            resp = await authenticated_request(
                self.creds, url, self.client_session, RequestType.get
            )
            results = json.loads(await resp.text())
            members = results.get("members", [])
            return members
        # handle errors if IAM group does not exist etc.
        except Exception as e:
            raise Exception(
                f"Error: Failed to get IAM members of IAM group `{group}`. Verify group exists and is configured correctly."
            ) from e

    async def get_db_users(self, instance_connection_name):
        """Get all database users of a Cloud SQL instance.

        Given a database instance and a Google Cloud project, get all the database
        users that belong to the database instance.

        Args:
            instance_connection_name: InstanceConnectionName namedTuple.
                (e.g. InstanceConnectionName(project='my-project', region='my-region',
                instance='my-instance'))

        Returns:
            users: List of all database users that belong to the Cloud SQL instance.
        """
        # build request to SQL Admin API
        project = instance_connection_name.project
        instance = instance_connection_name.instance
        url = f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{project}/instances/{instance}/users"

        try:
            # call the SQL Admin API
            resp = await authenticated_request(
                self.creds, url, self.client_session, RequestType.get
            )
            results = json.loads(await resp.text())
            users = results.get("items", [])
            return users
        except Exception as e:
            raise Exception(
                f"Error: Failed to get the database users for instance `{instance_connection_name}`. Verify instance connection name and instance details."
            ) from e

    async def insert_db_user(self, user_email, instance_connection_name):
        """Create DB user from IAM user.

        Given an IAM user's email, insert the IAM user as a DB user for Cloud SQL instance.

        Args:
            user_email: IAM users's email address.
            instance_connection_name: InstanceConnectionName namedTuple.
                (e.g. InstanceConnectionName(project='my-project', region='my-region',
                instance='my-instance'))
        """
        # build request to SQL Admin API
        project = instance_connection_name.project
        instance = instance_connection_name.instance
        url = f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{project}/instances/{instance}/users"
        user = {"name": user_email, "type": "CLOUD_IAM_USER"}

        try:
            # call the SQL Admin API
            resp = await authenticated_request(
                self.creds, url, self.client_session, RequestType.post, body=user
            )
            return
        except Exception as e:
            raise Exception(
                f"Error: Failed to add IAM user `{user_email}` to Cloud SQL database instance `{instance_connection_name.instance}`."
            ) from e

    async def get_database_version(self, instance_connection_name):
        """Get database version of a Cloud SQL instance.

        Args:
            instance_connection_name: InstanceConnectionName namedTuple.
                (e.g. InstanceConnectionName(project='my-project', region='my-region',
                instance='my-instance'))

        Returns:
            database_version: Database version of given Cloud SQL instance.
        """
        # build request to SQL Admin API
        project = instance_connection_name.project
        region = instance_connection_name.region
        instance = instance_connection_name.instance
        url = f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{project}/instances/{instance}"

        try:
            # call the SQL Admin API
            resp = await authenticated_request(
                self.creds, url, self.client_session, RequestType.get
            )
            results = json.loads(await resp.text())
            database_version = results.get("databaseVersion")
            logging.debug(
                "[%s:%s:%s] Database version found: %s"
                % (project, region, instance, database_version)
            )
            return DatabaseVersion(database_version)
        except ValueError as e:
            raise ValueError(
                f"Unsupported database version for instance `{instance}`. Current supported versions are: {list(DatabaseVersion.__members__.keys())}"
            ) from e
        except Exception as e:
            raise Exception(
                f"Error: Failed to get the database version for `{instance_connection_name}`. Verify instance connection name and instance details."
            ) from e


class RequestType(Enum):
    """Helper class for supported aiohttp request types."""

    get = 1
    post = 2


async def authenticated_request(creds, url, client_session, request_type, body=None):
    """Helper function to build authenticated aiohttp requests.

    Args:
        creds: OAuth2 credentials for authorizing requests.
        url: URL for aiohttp request.
        client_session: aiohttp ClientSession object.
        request_type: RequestType enum determining request type.
        body: (optional) JSON body for request.

    Return:
        Result from aiohttp request.
    """
    if not creds.valid:
        request = Request()
        creds.refresh(request)

    headers = {
        "Authorization": f"Bearer {creds.token}",
    }

    if request_type == RequestType.get:
        return await client_session.get(url, headers=headers, raise_for_status=True)
    elif request_type == RequestType.post:
        return await client_session.post(
            url, headers=headers, json=body, raise_for_status=True
        )
    else:
        raise ValueError(
            "Request type not recognized! " "Please verify RequestType is valid."
        )


async def get_users_with_roles(role_service, role):
    """Get mapping of group role grants on DB users.

    Args:
        role_service: A RoleService class instance.
        role: Name of IAM group role.

    Returns: List of all users who have the role granted to them.
    """
    role_grants = []
    grants = await role_service.fetch_role_grants(role)
    # loop through grants that are in tuple form (FROM_USER, TO_USER)
    for grant in grants:
        # add users who have role
        role_grants.append(grant[1])
    return role_grants


async def revoke_iam_group_role(
    role_service,
    role,
    users_with_roles_future,
    iam_users_future,
    database_type,
):
    """Revoke IAM group role from database users no longer in IAM group.

    Args:
        role_service: A RoleService class instance.
        role: IAM group role.
        users_with_roles_future: Future for list of database users who have group role.
        iam_users_future: Future for list of IAM users in IAM group.
        database_type: Type of database.
    """
    # await dependent tasks
    iam_users, users_with_roles = await asyncio.gather(
        iam_users_future, users_with_roles_future
    )

    if database_type.is_mysql():
        # truncate mysql_usernames
        iam_users = [mysql_username(user) for user in iam_users]

    # get list of users who have group role but are not in IAM group
    users_to_revoke = [
        user_with_role
        for user_with_role in users_with_roles
        if user_with_role not in iam_users
    ]
    # revoke group role from users no longer in IAM group
    await role_service.revoke_group_role(role, users_to_revoke)

    return users_to_revoke


async def grant_iam_group_role(
    role_service,
    role,
    users_with_roles_future,
    iam_users_future,
    database_type,
):
    """Grant IAM group role to IAM database users missing it.

    Args:
        role_service: A RoleService class instance.
        role: IAM group role.
        users_with_roles_future: Future for list of database users who have group role.
        iam_users_future: Future for list of IAM users in IAM group.
        database_type: Type of database.
    """
    # await dependent tasks
    iam_users, users_with_roles = await asyncio.gather(
        iam_users_future, users_with_roles_future
    )

    if database_type.is_mysql():
        # truncate mysql_usernames
        iam_users = [mysql_username(user) for user in iam_users]

    # find DB users who are part of IAM group that need role granted to them
    users_to_grant = [user for user in iam_users if user not in users_with_roles]
    await role_service.grant_group_role(role, users_to_grant)

    return users_to_grant


class GroupRoleMaxLengthError(Exception):
    """Error raised if group role exceeds database character limit"""

    def __init__(self, *args: Any) -> None:
        super(GroupRoleMaxLengthError, self).__init__(self, *args)


def verify_group_role_length(
    iam_groups: list, group_roles: Optional[dict], database_version: DatabaseVersion
) -> None:
    """Verify that group role names created or used by GroupSync do not
    exceed the character limit for the database.
    iam_groups: List of iam group emails for IAM groups to sync.
        (e.g. ["iam-group@test.com", "iam-group2@test.com"])
    sql_instances: List of instance connection names for Cloud SQL instances to sync.
        (e.g. ["<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>"])
        credentials: OAuth2 credentials.
    group_roles:(optional) Dict of IAM group emails as keys and group database
        role names as values. The group database role name is the database role
        that will be granted/revoked within GroupSync to each member of the
        corresponding IAM group. Group role names default to IAM group email
        without the domain (everything before the @, i.e "iam-group@test.com"
        would have group role name of "iam-group".
        (e.g.
            {
                "iam-group@test.com": "engineering",
                "iam-group2@test.com": "accounting"
            }
        )
    """
    # character limit for username/role for MySQL is 32, Postgres is 63
    char_limit = 32 if database_version.is_mysql() else 63
    for iam_group in iam_groups:
        # character count for group role
        char_role = len(group_roles.get(iam_group, mysql_username(iam_group)))
        if char_role > char_limit:
            raise GroupRoleMaxLengthError(
                f"Group database role for IAM group `{iam_group}` "
                f"would exceed character limit of {char_limit}, please specify"
                " request parameter `group_roles` to map group role to shorter"
                " length."
            )
