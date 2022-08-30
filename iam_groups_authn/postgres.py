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

# postgres.py contains all database specific functions for connecting
# and querying a postgreSQL database

import sqlalchemy
from google.cloud.sql.connector import connector
from google.cloud.sql.connector.instance_connection_manager import IPTypes
from iam_groups_authn.utils import RoleService, async_wrap
from google.auth.transport.requests import Request


def postgres_username(iam_email):
    """Get Postgres username from user or service account email.

    Given an IAM user or IAM service account email, format their Postgres
    database username accordingly. Do nothing for user emails, remove
    '.gserviceaccount.com' suffix from service account emails.

    Args:
        iam_email: An IAM user or service account email.

    Returns:
        username: The IAM user or service account Postgres DB username.
    """
    username = iam_email.removesuffix(".gserviceaccount.com")
    return username


class PostgresRoleService(RoleService):
    """Class for managing a Postgres DB user's role grants."""

    def __init__(self, db):
        """Initialize a PostgresRoleService object.

        Args:
            db: Database connection object.
        """
        self.db = db

    @async_wrap
    def fetch_role_grants(self, group_name):
        """Fetch mappings of group roles granted to DB users.

        Args:
            group_name: IAM group name prefix of email that is used as group role.

        Returns:
            results: List of results for given query.
        """
        # postgres query to get users with group role
        stmt = sqlalchemy.text(
            "SELECT pg_roles.rolname, (SELECT pg_roles.rolname FROM pg_roles WHERE oid = pg_auth_members.member) FROM pg_roles, pg_auth_members WHERE pg_auth_members.roleid = (SELECT oid FROM pg_roles WHERE rolname= :group_name) and pg_roles.rolname= :group_name"
        )
        # create connection to db instance
        with self.db.connect() as db_connection:
            # query users with roles
            results = db_connection.execute(stmt, {"group_name": group_name}).fetchall()
        return results

    @async_wrap
    def create_group_role(self, role):
        """Verify or create DB role.

        Given a group role, verify existance of role on DB or create new role
        to manage DB users.

        Args:
            role: Name of group role to be verified or created as new role.
        """
        # check if group role exists, otherwise create it
        check_stmt = sqlalchemy.text("SELECT 1 FROM pg_roles WHERE rolname= :role")
        stmt = sqlalchemy.text(f'CREATE ROLE "{role}"')
        # create connection to db instance
        with self.db.connect() as db_connection:
            # check if role already exists
            role_check = db_connection.execute(check_stmt, {"role": role}).fetchone()
            # if role does not exist, create it
            if not role_check:
                db_connection.execute(stmt)

    @async_wrap
    def grant_group_role(self, role, users):
        """Grant DB group role to DB users.

        Given a DB group role and a list of DB users, grant the DB role to each user.

        Args:
            role: Name of DB role to grant to users.
            users: List of DB users' usernames.
        """
        with self.db.connect() as db_connection:
            # if there are users to grant group role to, grant role to users
            if users:
                users = '"' + '", "'.join(users) + '"'
                stmt = sqlalchemy.text(f'GRANT "{role}" TO {users}')
                db_connection.execute(stmt)

    @async_wrap
    def revoke_group_role(self, role, users):
        """Revoke DB group role to DB users.

        Given a DB group role and a list of DB users, revoke the DB role from each user.

        Args:
            role: Name of DB role to revoke from users.
            users: List of DB users' usernames.
        """
        # create connection to db instance
        with self.db.connect() as db_connection:
            # if there are users to revoke group role from, revoke role from users
            if users:
                users = '"' + '", "'.join(users) + '"'
                stmt = sqlalchemy.text(f'REVOKE "{role}" FROM {users}')
                db_connection.execute(stmt)


def init_postgres_connection_engine(
    instance_connection_name, creds, ip_type=IPTypes.PUBLIC
):
    """Configure and initialize Postgres database connection pool.

    Configures the parameters for the database connection pool. Initiliazes the
    database connection pool using the Cloud SQL Python Connector.

    Args:
        instance_connection_name: Instance connection name of Cloud SQL instance.
            (e.g. "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>")
        creds: Credentials to get OAuth2 access token from, needed for IAM service
            account authentication to DB.
        ip_type: IP address type for instance connection.
            (IPTypes.PUBLIC or IPTypes.PRIVATE)
    Returns:
        A database connection pool instance.
    """
    db_config = {
        "pool_size": 2,
        "max_overflow": 2,
        "pool_timeout": 30,  # 30 seconds
        "pool_recycle": 1800,  # 30 minutes
    }
    # refresh credentials if not valid
    if not creds.valid:
        request = Request()
        creds.refresh(request)

    # service account to access DB, postgres removes suffix
    service_account_email = (creds.service_account_email).removesuffix(
        ".gserviceaccount.com"
    )
    # build connection for db using Python Connector
    connection = lambda: connector.connect(
        instance_connection_name,
        "pg8000",
        ip_types=ip_type,
        user=service_account_email,
        db="postgres",
        enable_iam_auth=True,
    )

    # create connection pool
    pool = sqlalchemy.create_engine(
        "postgresql+pg8000://", creator=connection, **db_config
    )
    return pool
