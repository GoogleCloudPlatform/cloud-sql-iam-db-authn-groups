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

import os
from quart import Quart
from quart.utils import run_sync
import asyncio
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine
import json
from google.auth import default, iam
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from collections import defaultdict
from typing import NamedTuple
from functools import partial

# URI for OAuth2 credentials
TOKEN_URI = "https://accounts.google.com/o/oauth2/token"

# define scopes
IAM_SCOPES = ["https://www.googleapis.com/auth/admin.directory.group.member.readonly"]
SQL_SCOPES = ["https://www.googleapis.com/auth/sqlservice.admin"]

app = Quart(__name__)


class InstanceConnectionName(NamedTuple):
    """A class to manage instance connection names.

    Args:
        project (str): Project name that instance belongs to.
        region (str): Region where instance is located.
        instance (str): Name of instance.
    """

    project: str
    region: str
    instance: str


class RoleService:
    """Class for managing a DB user's role grants."""

    def __init__(self, db):
        """Initialize a RoleService object.

        Args:
            db: Database connection object.
        """
        self.db = db

    async def fetch_user_grants(self, user):
        """Fetch DB grants of a DB user.

        Args:
            user: Username of a DB user.

        Returns:
            results: List of grants for the DB user.
        """
        # query roles granted to user
        stmt = sqlalchemy.text("SHOW GRANTS FOR :user")
        results = (await self.db.execute(stmt, {"user": user})).fetchall()
        return results

    async def fetch_role_grants(self, group_name):
        """Fetch mappings of group roles granted to DB users.

        Args:
            group_name: IAM group name prefix of email that is used as group role.

        Returns:
            results: List of results for given query.
        """
        # query role_edges table
        stmt = sqlalchemy.text(
            "SELECT FROM_USER, TO_USER FROM mysql.role_edges WHERE FROM_USER= :group_name"
        )
        results = (await self.db.execute(stmt, {"group_name": group_name})).fetchall()
        return results

    async def create_group_role(self, group):
        """Verify or create DB role.

        Given a group name, verify existance of DB role or create new DB role matching
        name of group to manage DB users.

        Args:
            db: Database connection pool instance.
            group: Name of group to be verified as role or created as new role.
        """
        stmt = sqlalchemy.text("CREATE ROLE IF NOT EXISTS :role")
        await self.db.execute(stmt, {"role": group})

    async def grant_group_role(self, role, users):
        """Grant DB group role to DB users.

        Given a DB group role and a list of DB users, grant the DB role to each user.

        Args:
            db: Database connection pool instance.
            role: Name of DB role to grant to users.
            users: List of DB users' usernames.
        """
        stmt = sqlalchemy.text("GRANT :role TO :user")
        for user in users:
            await self.db.execute(stmt, {"role": role, "user": user})

    async def revoke_group_role(self, role, users):
        """Revoke DB group role to DB users.

        Given a DB group role and a list of DB users, revoke the DB role from each user.

        Args:
            db: Database connection pool instance.
            role: Name of DB role to revoke from users.
            users: List of DB users' usernames.
        """
        stmt = sqlalchemy.text("REVOKE :role FROM :user")
        for user in users:
            await self.db.execute(stmt, {"role": role, "user": user})


def load_config(filename="config.json"):
    """Load in params from json config file.

    Loading in configurable parameters for service which are Cloud SQL Instance
    names and IAM Group names.

    Example config file:
    {
        "sql_instances" : ["my-project:my-region:my-instance", "my-other-project:my-other-region:my-other-instance"],
        "iam_groups" : ["group@example.com", "othergroup@example.com"],
        "admin_email" : "admin@example.com"
    }

    Args:
        filename: The name of the configurable json file.

    Returns:
        sql_instances: List of all Cloud SQL instances to configure.
        iam_groups: List of all IAM Groups to manage DB users of.
        admin_email: Email of user with proper admin privileges for Google Workspace, needed
            for calling Directory API to fetch IAM users within IAM groups.
    """
    with open(filename) as json_file:
        config = json.load(json_file)

    sql_instances = config["sql_instances"]
    iam_groups = config["iam_groups"]
    admin_email = config["admin_email"]

    # verify config params are not empty
    if sql_instances is None or sql_instances == []:
        raise ValueError(build_error_message("sql_instances"))
    if iam_groups is None or iam_groups == []:
        raise ValueError(build_error_message("iam_groups"))
    if admin_email is None or admin_email == "":
        raise ValueError(build_error_message("admin_email"))
    return sql_instances, iam_groups, admin_email


def build_error_message(var_name):
    """Function to help build error messages for missing config variables.

    Args:
        var_name: String of variable name that is missing in config.

    Returns:
        message: Constructed error message to be outputted.
    """
    message = (
        f"\nNo valid {var_name} configured, please verify your config.json.\n"
        '\nValid configuration should look like:\n\n{\n "sql_instances" : ['
        '"my-project:my-region:my-instance",'
        ' "my-other-project:my-other-region:my-other-instance"],\n "iam_groups" : '
        '["group@example.com", "othergroup@example.com"],\n "admin_email" : '
        '"admin@example.com"\n}\n\nYour configuration is '
        f"missing the `{var_name}` key."
    )
    return message


def init_connection_engine(instance_connection_name, creds):
    """Configure and initialize database connection pool.

    Configures the parameters for the database connection pool. Initiliazes the
    database connection pool either through TCP (private IP) or via Unix socket
    (public IP).

    Args:
        instance_connection_name: Instance connection name of Cloud SQL instance.
            (e.g. "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>")
        creds: Credentials to get OAuth2 access token from, needed for IAM service
            account authentication to DB.
    """
    db_config = {
        "pool_size": 5,
        "max_overflow": 2,
        "pool_timeout": 30,  # 30 seconds
        "pool_recycle": 1800,  # 30 minutes
    }

    # service account email to access DB, mysql truncates usernames to before '@' sign
    service_account_email = mysql_username(creds.service_account_email)
    return init_unix_connection_engine(
        instance_connection_name, db_config, service_account_email, creds
    )


def init_unix_connection_engine(
    instance_connection_name, db_config, service_account_email, creds
):
    """Load and initialize database connection pool via Unix socket connection.

    Loads in the parameters for the database connection pool. Initiliazes
    the database connection pool through Unix socket which is recommended route for
    public IP.

    Args:
        instance_connection_name: Instance connection name of Cloud SQL instance.
            (e.g. "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>")
        db_config: A dict mapping database config parameters to their corresponding
            values.
        service_account_email: Email address of service account to use for connecting
            to instance.
        creds: Credentials to get OAuth2 access token from, needed for IAM service
            account authentication to DB.

    Returns:
        A database connection pool instance.
    """
    # config for service account DB user
    db_user = service_account_email
    db_pass = str(creds.token)
    db_name = ""
    db_socket_dir = os.environ.get("DB_SOCKET_DIR", "/cloudsql")

    pool = create_async_engine(
        # Equivalent URL:
        # mysql+pymysql://<db_user>:<db_pass>@/<db_name>?unix_socket=<socket_path>/<cloud_sql_instance_name>
        sqlalchemy.engine.url.URL.create(
            drivername="mysql+aiomysql",
            username=db_user,  # e.g. "my-database-user"
            password=db_pass,  # e.g. "my-database-password"
            database=db_name,  # e.g. "my-database-name"
            query={
                "unix_socket": "{}/{}".format(
                    db_socket_dir, instance_connection_name  # e.g. "/cloudsql"
                )  # i.e "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>"
            },
        ),
        **db_config,
    )
    return pool


async def get_iam_users(user_service, groups):
    """Get list of all IAM users within IAM groups.

    Given a list of IAM groups, get all IAM users that are members within one or
    more of the groups or a nested child group.

    Args:
        user_service: Instance of a UserService object.
        groups: List of IAM groups. (e.g., ["group@example.com", "abc@example.com"])

    Returns:
        iam_users: Set containing all IAM users found within IAM groups.
    """
    # keep track of iam users using set for no duplicates
    iam_users = defaultdict(list)
    # loop through groups and get their IAM users
    for group in groups:
        group_queue = [group]
        # set initial groups searched to input groups
        searched_groups = group_queue.copy()
        group_users = set()
        while group_queue:
            current_group = group_queue.pop(0)
            # get all members of current IAM group
            members_partial = partial(user_service.get_group_members, current_group)
            members = await run_sync(members_partial)()
            # check if member is a group, otherwise they are a user
            for member in members:
                if member["type"] == "GROUP":
                    if member["email"] not in searched_groups:
                        # add current group to searched groups
                        searched_groups.append(member["email"])
                        # add group to queue
                        group_queue.append(member["email"])
                elif member["type"] == "USER":
                    # add user to list of group users
                    group_users.add(member["email"])
                else:
                    continue
        # only add to dict if group has members, allows skipping of not valid groups
        if group_users:
            iam_users[group] = group_users

    return iam_users


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


async def get_instance_users(user_service, instance_connection_names):
    """Get users that belong to each Cloud SQL instance.

    Given a list of Cloud SQL instance names and a Google Cloud project, get a list
    of database users that belong to each instance.

    Args:
        user_service: A UserService object for calling SQL admin APIs.
        instance_connection_names: List of Cloud SQL instance connection names.
            (e.g., ["my-project:my-region:my-instance", "my-project:my-region:my-other-instance"])

    Returns:
        db_users: A dict with the instance names mapping to their list of database users.
    """
    # create dict to hold database users of each instance
    db_users = defaultdict(list)
    for connection_name in instance_connection_names:
        get_users = partial(
            user_service.get_db_users,
            InstanceConnectionName(*connection_name.split(":")),
        )
        users = await run_sync(get_users)()
        for user in users:
            db_users[connection_name].append(user["name"])
    return db_users


async def manage_instance_roles(instance_connection_name, iam_users, creds):
    """Function to manage database instance roles.

    Manage DB roles within database instance which includes: connect to instance,
    verify/create group roles, add roles to DB users who are missing them.

    Args:
        instance_connection_name: Instance connection name of Cloud SQL instance.
            (e.g. "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>")
        iam_users: Set containing all IAM users found within IAM groups.
        creds: OAuth2 credentials with SQL scopes applied.
    """
    db = init_connection_engine(instance_connection_name, creds)
    # create connection to db instance
    async with db.connect() as db_connection:
        role_service = RoleService(db_connection)
        users_with_roles = await get_users_with_roles(role_service, iam_users.keys())
        for group, users in iam_users.items():
            # mysql role does not need email part and can be truncated
            role = mysql_username(group)
            # truncate mysql_usernames
            mysql_usernames = [mysql_username(user) for user in users]
            await role_service.create_group_role(role)
            users_missing_role = await get_users_missing_role(role_service, role, users)
            print(
                f"Users missing role `{role}` for instance `{instance_connection_name}`: {users_missing_role}"
            )
            await role_service.grant_group_role(role, users_missing_role)
            print(
                f"Granted the following users the role `{role}` on instance `{instance_connection_name}`: {users_missing_role}"
            )
            # get list of users who have group role but are not in IAM group
            users_to_revoke = [
                user_with_role
                for user_with_role in users_with_roles[role]
                if user_with_role not in mysql_usernames
            ]
            await role_service.revoke_group_role(role, users_to_revoke)
            print(
                f"Revoked the following users the role `{role}` on instance `{instance_connection_name}`: {users_to_revoke}"
            )
    return


async def get_users_missing_role(role_service, role, users):
    """Find DB users' missing DB role.

    Given a list of DB users, and a specific DB role, find all DB users that don't have the
    role granted to them.

    Args:
        role_service: A RoleService class object.
        role: Name of DB role to query each user for.
        users: List of DB users' usernames.

    Returns:
        users_missing_role: List of DB usernames for users who are missing role.
    """
    users_missing_role = []
    for user in users:
        # mysql usernames are truncated to before '@' sign
        user = mysql_username(user)
        # fetch granted DB roles of user
        results = await role_service.fetch_user_grants(user)
        has_grant = False
        # look for role among roles granted to user
        for result in results:
            result = str(result)
            if result.find(f"`{role}`") >= 0:
                has_grant = True
                break
        # if user doesn't have role add them to list
        if not has_grant:
            users_missing_role.append(user)
    return users_missing_role


async def get_users_with_roles(role_service, group_names):
    """Get mapping of group role grants on DB users.

    Args:
        role_service: A RoleService class instance.
        group_names: List of all IAM group names.

    Returns: Dict mapping group role to all users who have the role granted to them.
    """
    role_grants = defaultdict(list)
    for group_name in group_names:
        group_name = mysql_username(group_name)
        grants = await role_service.fetch_role_grants(group_name)
        # loop through grants that are in tuple form (FROM_USER, TO_USER)
        for grant in grants:
            # filter into dict for easier access later
            role, user = grant
            role_grants[role].append(user)
    return role_grants


def delegated_credentials(creds, scopes, admin_user=None):
    """Update default credentials.

    Based on scopes and domain delegation, update OAuth2 default credentials
    accordingly.

    Args:
        creds: Default OAuth2 credentials.
        scopes: List of scopes for the credentials to limit access.
        admin_user: Email of admin user, required for domain delegation credentials.

    Returns:
        updated_credentials: Updated OAuth2 credentials with scopes and domain
        delegation applied.
    """
    try:
        # First try to update credentials using service account key file
        updated_credentials = creds.with_subject(admin_user).with_scopes(scopes)
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
            signer, service_acccount_email, TOKEN_URI, scopes=scopes, subject=admin_user
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


def mysql_username(iam_email):
    """Get MySQL DB username from user or group email.

    Given an IAM user or IAM group's email, get their corresponding MySQL DB username which is a
    truncated version of their email. (everything before the '@' sign)

    Args:
        iam_email: An IAM user or group email.

    Returns:
        username: The IAM user or group's MySQL DB username.
    """
    username = iam_email.split("@")[0]
    return username


@app.route("/", methods=["GET"])
def sanity_check():
    return "App is running!"


@app.route("/run", methods=["GET"])
async def run():
    # read in config params
    sql_instances, iam_groups, admin_email = load_config("config.json")
    # grab default creds from cloud run service account
    creds, project = default()
    # update default credentials with IAM SCOPE and domain delegation
    iam_creds = delegated_credentials(creds, IAM_SCOPES, admin_email)
    # update default credentials with Cloud SQL scopes
    sql_creds = delegated_credentials(creds, SQL_SCOPES)

    # create UserService object for API calls
    user_service = UserService(sql_creds, iam_creds)

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

    # for each instance add IAM group roles to manage permissions and grant roles if need be
    instance_coroutines = [
        manage_instance_roles(instance, iam_users, sql_creds)
        for instance in sql_instances
    ]
    await asyncio.gather(*instance_coroutines)
    return "IAM DB Groups Authn has run successfully!"
