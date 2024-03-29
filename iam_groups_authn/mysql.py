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

# mysql.py contains all database specific functions for connecting
# and querying a MySQL database

import sqlalchemy
from google.cloud.sql.connector import connector
from google.cloud.sql.connector.instance_connection_manager import IPTypes
from iam_groups_authn.utils import RoleService, async_wrap
from google.auth.transport.requests import Request


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


class MysqlRoleService(RoleService):
    """Class for managing a MySQL DB user's role grants."""

    def __init__(self, db):
        """Initialize a MysqlRoleService object.

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
        # mysql query to get users with group role
        stmt = sqlalchemy.text(
            "SELECT FROM_USER, TO_USER FROM mysql.role_edges WHERE FROM_USER= :group_name"
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
        stmt = sqlalchemy.text("CREATE ROLE IF NOT EXISTS :role")
        with self.db.connect() as db_connection:
            db_connection.execute(stmt, {"role": role})

    @async_wrap
    def grant_group_role(self, role, users):
        """Grant DB group role to DB users.

        Given a DB group role and a list of DB users, grant the DB role to each user.

        Args:
            role: Name of DB role to grant to users.
            users: List of DB users' usernames.
        """
        # create connection to db instance
        with self.db.connect() as db_connection:
            stmt = sqlalchemy.text("GRANT :role TO :user")
            for user in users:
                db_connection.execute(stmt, {"role": role, "user": user})

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
            stmt = sqlalchemy.text("REVOKE :role FROM :user")
            for user in users:
                db_connection.execute(stmt, {"role": role, "user": user})


def init_mysql_connection_engine(
    instance_connection_name, creds, ip_type=IPTypes.PUBLIC
):
    """Configure and initialize MySQL database connection pool.

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

    # service account email to access DB, mysql truncates usernames to before '@' sign
    service_account_email = mysql_username(creds.service_account_email)
    # build connection for db using Python Connector
    connection = lambda: connector.connect(
        instance_connection_name,
        "pymysql",
        ip_types=ip_type,
        user=service_account_email,
        password=str(creds.token),
        db="",
        enable_iam_auth=False,
    )

    # create connection pool
    pool = sqlalchemy.create_engine("mysql+pymysql://", creator=connection, **db_config)
    return pool
