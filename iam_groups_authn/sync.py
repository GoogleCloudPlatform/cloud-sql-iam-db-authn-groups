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

from google.auth import iam
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from collections import defaultdict
from google.cloud.sql.connector.instance_connection_manager import IPTypes
from iam_groups_authn.sql_admin import (
    init_connection_engine,
    RoleService,
    get_users_with_roles,
)
from iam_groups_authn.mysql import mysql_username

# URI for OAuth2 credentials
TOKEN_URI = "https://accounts.google.com/o/oauth2/token"


class UserService:
    """Helper class for building googleapis service calls."""

    def __init__(self, sql_creds, iam_creds):
        """Initialize UserService instance.

        Args:
            sql_creds: OAuth2 credentials to call Cloud SQL Admin APIs.
            iam_creds: OAuth2 credentials to call Directory Admin APIs
        """
        self.sql_creds = sql_creds
        self.iam_creds = iam_creds

    def get_group_members(self, group):
        """Get all members of an IAM group.

        Given an IAM group, get all members (groups or users) that belong to the
        group.

        Args:
            group (str): A single IAM group identifier key (name, email, ID).

        Returns:
            members: List of all members (groups or users) that belong to the IAM group.
        """
        # build service to call Admin SDK Directory API
        service = build("admin", "directory_v1", credentials=self.iam_creds)

        try:
            # call the Admin SDK Directory API
            results = service.members().list(groupKey=group).execute()
            members = results.get("members", [])
            return members
        # handle errors if IAM group does not exist etc.
        except HttpError as e:
            print(f"Could not get IAM group `{group}`. Error: {e}")
            return []

    def get_db_users(self, instance_connection_name):
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
        # build service to call SQL Admin API
        service = build("sqladmin", "v1beta4", credentials=self.sql_creds)
        results = (
            service.users()
            .list(
                project=instance_connection_name.project,
                instance=instance_connection_name.instance,
            )
            .execute()
        )
        users = results.get("items", [])
        return users

    def insert_db_user(self, user_email, instance_connection_name):
        """Create DB user from IAM user.

        Given an IAM user's email, insert the IAM user as a DB user for Cloud SQL instance.

        Args:
            user_email: IAM users's email address.
            instance_connection_name: InstanceConnectionName namedTuple.
                (e.g. InstanceConnectionName(project='my-project', region='my-region',
                instance='my-instance'))
        """
        # build service to call SQL Admin API
        service = build("sqladmin", "v1beta4", credentials=self.sql_creds)
        user = {"name": user_email, "type": "CLOUD_IAM_USER"}
        try:
            results = (
                service.users()
                .insert(
                    project=instance_connection_name.project,
                    instance=instance_connection_name.instance,
                    body=user,
                )
                .execute()
            )
        except Exception as e:
            print(
                f"Could not add IAM user `{user_email}` to DB Instance `{instance_connection_name.instance}`. Error: {e}"
            )
        return


async def manage_instance_users(
    instance_connection_name, iam_users, creds, ip_type=IPTypes.PUBLIC
):
    """Function to manage database instance users.

    Manage DB users within database instance which includes: connect to instance,
    verify/create group roles, add roles to DB users who are missing them,
    and revoke roles from users no longer in IAM group.

    Args:
        instance_connection_name: Instance connection name of Cloud SQL instance.
            (e.g. "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>")
        iam_users: Set containing all IAM users found within IAM groups.
        creds: OAuth2 credentials with SQL scopes applied.
        ip_type: IP address type for instance connection.
            (IPTypes.PUBLIC or IPTypes.PRIVATE)
    """
    db = init_connection_engine(instance_connection_name, creds, ip_type)
    # create connection to db instance
    with db.connect() as db_connection:
        role_service = RoleService(db_connection)
        await manage_user_roles(role_service, iam_users)
    return


async def manage_user_roles(role_service, iam_users):
    """Manage group role permissions for DB users.

    Create, grant, revoke proper IAM group role permissions to database users.

    Args:
        role_service: A RoleService class object for accessing grants in db.
        iam_users: Set containing all IAM users found within IAM groups.
    """
    users_with_roles = await get_users_with_roles(role_service, iam_users.keys())
    for group, users in iam_users.items():
        # mysql role does not need email part and can be truncated
        role = mysql_username(group)
        # truncate mysql_usernames
        mysql_usernames = [mysql_username(user) for user in users]
        # create or verify group role exists
        await role_service.create_group_role(role)
        # find DB users who are part of IAM group that need role granted to them
        users_to_grant = [
            username
            for username in mysql_usernames
            if username not in users_with_roles[role]
        ]
        await role_service.grant_group_role(role, users_to_grant)
        # get list of users who have group role but are not in IAM group
        users_to_revoke = [
            user_with_role
            for user_with_role in users_with_roles[role]
            if user_with_role not in mysql_usernames
        ]
        # revoke group role from users no longer in IAM group
        await role_service.revoke_group_role(role, users_to_revoke)


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
    except Exception:
        raise

    return updated_credentials


def get_users_to_add(iam_users, instance_users):
    """Find IAM users who are missing as DB users.

    Given a dict mapping IAM groups to their IAM users, and a dict mapping Cloud SQL
    instances to their DB users, find IAM users who are missing their corresponding DB user.

    Args:
        iam_users: Dict where key is IAM group name and mapped value is list of that group's
            IAM users. (e.g. iam_users["example-group@abc.com] = ["user1", "user2", "user3"])
        instance_users: Dict where key is instance name and mapped value is list of that
            instance's DB users.(e.g. instance_users["my-instance"] = ["db-user1", "db-user2"])

    Returns:
        missing_db_users: Dict where key is instance name and mapped value is set of DB user's
            needing to be inserted into instance.
    """
    missing_db_users = defaultdict(set)
    for group, users in iam_users.items():
        for instance, db_users in instance_users.items():
            missing_users = [
                user for user in users if mysql_username(user) not in db_users
            ]
            if len(missing_users) > 0:
                for user in missing_users:
                    missing_db_users[instance].add(user)
    return missing_db_users
