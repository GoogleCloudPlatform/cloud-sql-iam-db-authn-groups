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
import sqlalchemy
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Quart(__name__)


def load_config(filename="config.json"):
    """Load in params from json config file.

    Loading in configurable parameters for service which are Cloud SQL Instance
    names and IAM Group names.

    Example config file:
    {
        "sql_instances" : ["my-instance", "my-other-instance"],
        "iam_groups" : ["group@example.com", "othergroup@example.com"]
    }

    Args:
        filename: The name of the configurable json file.

    Returns:
        sql_instances: List of all Cloud SQL instances to configure.
        iam_groups: List of all IAM Groups to manage DB users of.
    """
    with open(filename) as json_file:
        config = json.load(json_file)

    sql_instances = config["sql_instances"]
    iam_groups = config["iam_groups"]

    # verify config params are not empty
    if sql_instances is None or sql_instances == []:
        raise ValueError(
            '\nNo valid Cloud SQL instances configured, please verify your config.json.\n'
            '\nValid configuration should look like:\n\n{\n "sql_instances" : ['
            '"my-instance", "my-other-instance"],\n "iam_groups" : ["group@example.com"'
            ', "othergroup@example.com"]\n}\n\nYour configuration is missing the '
            '`sql_instances` key.'
        )
    if iam_groups is None or iam_groups == []:
        raise ValueError(
            '\nNo valid Cloud SQL instances configured, please verify your config.json.\n'
            '\nValid configuration should look like:\n\n{\n "sql_instances" : ['
            '"my-instance", "my-other-instance"],\n "iam_groups" : ["group@example.com"'
            ', "othergroup@example.com"]\n}\n\nYour configuration is missing the '
            '`iam_groups` key.'
        )
    return sql_instances, iam_groups


def init_connection_engine():
    """Configure and initialize database connection pool.

    Configures the parameters for the database connection pool. Initiliazes the
    database connection pool either through TCP (private IP) or via Unix socket
    (public IP).
    """
    db_config = {
        "pool_size": 5,
        "max_overflow": 2,
        "pool_timeout": 30,  # 30 seconds
        "pool_recycle": 1800,  # 30 minutes
    }

    if os.environ.get("DB_HOST"):
        return init_tcp_connection_engine(db_config)
    else:
        return init_unix_connection_engine(db_config)


def init_tcp_connection_engine(db_config):
    """Load and initialize database connection pool via TCP connection.

    Loads in the parameters for the database connection pool. Initiliazes the
    database connection pool through TCP which is recommended route for private IP.

    Args:
        db_config: A dict mapping database config parameters to their corresponding
            values.

    Returns:
        A database connection pool instance.
    """
    db_user = os.environ["DB_USER"]
    db_pass = os.environ["DB_PASS"]
    db_name = os.environ["DB_NAME"]
    db_host = os.environ["DB_HOST"]

    # Extract host and port from db_host
    host_args = db_host.split(":")
    db_hostname, db_port = host_args[0], int(host_args[1])

    pool = sqlalchemy.create_engine(
        # Equivalent URL:
        # mysql+pymysql://<db_user>:<db_pass>@<db_host>:<db_port>/<db_name>
        sqlalchemy.engine.url.URL.create(
            drivername="mysql+pymysql",
            username=db_user,  # e.g. "my-database-user"
            password=db_pass,  # e.g. "my-database-password"
            host=db_hostname,  # e.g. "127.0.0.1"
            port=db_port,  # e.g. 3306
            database=db_name,  # e.g. "my-database-name"
        ),
        **db_config,
    )
    return pool


def init_unix_connection_engine(db_config):
    """Load and initialize database connection pool via Unix socket connection.

    Loads in the parameters for the database connection pool. Initiliazes
    the database connection pool through Unix socket which is recommended route for
    public IP.

    Args:
        db_config: A dict mapping database config parameters to their corresponding
            values.

    Returns:
        A database connection pool instance.
    """
    db_user = os.environ["DB_USER"]
    db_pass = os.environ["DB_PASS"]
    db_name = os.environ["DB_NAME"]
    db_socket_dir = os.environ.get("DB_SOCKET_DIR", "/cloudsql")
    cloud_sql_connection_name = os.environ["CLOUD_SQL_CONNECTION_NAME"]

    pool = sqlalchemy.create_engine(
        # Equivalent URL:
        # mysql+pymysql://<db_user>:<db_pass>@/<db_name>?unix_socket=<socket_path>/<cloud_sql_instance_name>
        sqlalchemy.engine.url.URL.create(
            drivername="mysql+pymysql",
            username=db_user,  # e.g. "my-database-user"
            password=db_pass,  # e.g. "my-database-password"
            database=db_name,  # e.g. "my-database-name"
            query={
                "unix_socket": "{}/{}".format(
                    db_socket_dir, cloud_sql_connection_name  # e.g. "/cloudsql"
                )  # i.e "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>"
            },
        ),
        **db_config,
    )
    return pool


def get_iam_users(groups, creds):
    """Get list of all IAM users within IAM groups.

    Given a list of IAM groups, get all IAM users that are members within one or
    more of the groups or a nested child group.

    Args:
        groups: List of IAM groups. (e.g., ["group@example.com", "abc@example.com"])
        creds: Credentials from service account to call Admin SDK Directory API.

    Returns:
        iam_users: Set containing all IAM users found within IAM groups.
    """
    # keep track of iam users using set for no duplicates
    iam_users = set()
    # set initial groups searched to input groups
    searched_groups = groups.copy()
    # continue while there are groups to get users from
    while groups:
        group = groups.pop(0)
        # get all members of IAM group
        members = get_group_members(group, creds)
        # check if member is a group, otherwise they are a user
        for member in members:
            if member["type"] == "GROUP":
                if member["email"] not in searched_groups:
                    # add current group to searched groups
                    searched_groups.append(member["email"])
                    # add group to queue
                    groups.append(member["email"])
            else:
                # add user to list of group users
                iam_users.add(member["email"])
    return iam_users


def get_group_members(group, creds):
    """Get all members of an IAM group.

    Given an IAM group key, get all members (groups or users) that belong to the
    group.

    Args:
        group (str): A single IAM group identifier key (name, email, ID).
        creds: Credentials from service account to call Admin SDK Directory API.

    Returns:
        members: List of all members (groups or users) that belong to the IAM group.
    """
    # build service to call Admin SDK Directory API
    service = build("admin", "directory_v1", credentials=creds)
    # call the Admin SDK Directory API
    results = service.members().list(groupKey=group).execute()
    members = results.get("members", [])
    return members


# initialize db connection pool
db = init_connection_engine()

# read in config params
sql_instances, iam_groups = load_config("config.json")

# get oauth credentials
SCOPES = ["https://www.googleapis.com/auth/admin.directory.group.member.readonly"]
SERVICE_ACCOUNT_FILE = os.environ["SERVICE_ACCOUNT_PATH"]
credentials = service_account.Credentials.from_service_account_file(
    filename=SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
    subject=os.environ["DIRECTORY_ADMIN_SUBJECT"],
)


@app.route("/", methods=["GET"])
def get_time():
    with db.connect() as conn:
        current_time = conn.execute("SELECT NOW()").fetchone()
        print(f"Time: {str(current_time[0])}")
    return str(current_time[0])
