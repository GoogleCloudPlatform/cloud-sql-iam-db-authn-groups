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
from google.auth import iam
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from iam_groups_authn.mysql import mysql_username
import json
from aiohttp import ClientSession
from enum import Enum
import logging

# URI for OAuth2 credentials
TOKEN_URI = "https://accounts.google.com/o/oauth2/token"


class UserService:
    """Helper class for building googleapis service calls."""

    def __init__(self, creds):
        """Initialize UserService instance.

        Args:
            creds: OAuth2 credentials to call admin APIs.
        """
        self.creds = creds
        self.client_session = ClientSession(
            headers={"Content-Type": "application/json"}
        )

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
            return database_version
        except Exception as e:
            raise Exception(
                f"Error: Failed to get the database version for `{instance_connection_name}`. Verify instance connection name and instance details."
            ) from e

    def __del__(self):
        """Deconstructor for UserService to close ClientSession and have
        graceful exit.
        """

        async def deconstruct():
            if not self.client_session.closed:
                await self.client_session.close()

        asyncio.run_coroutine_threadsafe(deconstruct(), loop=asyncio.get_event_loop())


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


def get_credentials(creds, scopes):
    """Update default credentials.

    Based on scopes, update OAuth2 default credentials
    accordingly.

    Args:
        creds: Default OAuth2 credentials.
        scopes: List of scopes for the credentials to limit access.

    Returns:
        updated_credentials: Updated OAuth2 credentials with scopes applied.
    """
    try:
        # First try to update credentials using service account key file
        updated_credentials = creds.with_scopes(scopes)
        # if not valid refresh credentials
        if not updated_credentials.valid:
            request = Request()
            updated_credentials.refresh(request)
    except AttributeError:
        # Exception is raised if we are using default credentials (e.g. Cloud Run)
        request = Request()
        creds.refresh(request)
        service_acccount_email = creds.service_account_email
        signer = iam.Signer(request, creds, service_acccount_email)
        updated_credentials = service_account.Credentials(
            signer, service_acccount_email, TOKEN_URI, scopes=scopes
        )
        # if not valid, refresh credentials
        if not updated_credentials.valid:
            updated_credentials.refresh(request)
    except Exception as e:
        raise Exception(
            "Error: Failed to get proper credentials for service. Verify service account used to run service."
        ) from e

    return updated_credentials


def get_users_to_add(iam_users, db_users):
    """Find IAM users who are missing as DB users.

    Given a list of IAM users, and a list database users, find the IAM users
    who are missing their corresponding DB user.

    Args:
        iam_users: List of that group's IAM users. (e.g. ["user1", "user2", "user3"])
        db_users: List of an instance's database users. (e.g. ["db-user1", "db-user2"])

    Returns:
        missing_db_users: Set of names of DB user's needing to be inserted into instance.
    """
    missing_db_users = [
        user for user in iam_users if mysql_username(user) not in db_users
    ]
    return set(missing_db_users)


async def revoke_iam_group_role(
    role_service,
    role,
    users_with_roles_future,
    iam_users_future,
):
    """Revoke IAM group role from database users no longer in IAM group.

    Args:
        role_service: A RoleService class instance.
        role: IAM group role.
        users_with_roles_future: Future for list of database users who have group role.
        iam_users_future: Future for list of IAM users in IAM group.
    """
    # await dependent tasks
    iam_users = await iam_users_future
    users_with_roles = await users_with_roles_future

    # truncate mysql_usernames
    mysql_usernames = [mysql_username(user) for user in iam_users]
    # get list of users who have group role but are not in IAM group
    users_to_revoke = [
        user_with_role
        for user_with_role in users_with_roles
        if user_with_role not in mysql_usernames
    ]
    # revoke group role from users no longer in IAM group
    await role_service.revoke_group_role(role, users_to_revoke)

    return users_to_revoke


async def grant_iam_group_role(
    role_service,
    role,
    users_with_roles_future,
    iam_users_future,
):
    """Grant IAM group role to IAM database users missing it.

    Args:
        role_service: A RoleService class instance.
        role: IAM group role.
        users_with_roles_future: Future for list of database users who have group role.
        iam_users_future: Future for list of IAM users in IAM group.
    """
    # await dependent tasks
    iam_users = await iam_users_future
    users_with_roles = await users_with_roles_future

    # truncate mysql_usernames
    mysql_usernames = [mysql_username(user) for user in iam_users]
    # find DB users who are part of IAM group that need role granted to them
    users_to_grant = [
        username for username in mysql_usernames if username not in users_with_roles
    ]
    await role_service.grant_group_role(role, users_to_grant)

    return users_to_grant
