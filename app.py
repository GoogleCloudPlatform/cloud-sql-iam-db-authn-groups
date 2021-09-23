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
from google.auth import default, iam
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from collections import defaultdict

# URI for OAuth2 credentials
TOKEN_URI = "https://accounts.google.com/o/oauth2/token"

# define scopes
IAM_SCOPES = ["https://www.googleapis.com/auth/admin.directory.group.member.readonly"]
SQL_SCOPES = ["https://www.googleapis.com/auth/sqlservice.admin"]

app = Quart(__name__)


def load_config(filename="config.json"):
    """Load in params from json config file.

    Loading in configurable parameters for service which are Cloud SQL Instance
    names and IAM Group names.

    Example config file:
    {
        "sql_instances" : ["my-project:my-region:my-instance", "my-other-project:my-other-region:my-other-instance"],
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
        raise ValueError(build_error_message("sql_instances"))
    if iam_groups is None or iam_groups == []:
        raise ValueError(build_error_message("iam_groups"))
    return sql_instances, iam_groups


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
    service_account_email = creds.service_account_email.split("@")[0]
    if os.environ.get("DB_HOST"):
        return init_tcp_connection_engine(db_config, service_account_email, creds)
    else:
        return init_unix_connection_engine(
            instance_connection_name, db_config, service_account_email, creds
        )


def init_tcp_connection_engine(db_config, service_acount_email, creds):
    """Load and initialize database connection pool via TCP connection.

    Loads in the parameters for the database connection pool. Initiliazes the
    database connection pool through TCP which is recommended route for private IP.

    Args:
        db_config: A dict mapping database config parameters to their corresponding
            values.

    Returns:
        A database connection pool instance.
    """
    db_user = service_acount_email
    db_pass = str(creds.token)
    db_name = ""
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
    cloud_sql_connection_name = instance_connection_name

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
        creds: Credentials to call Admin SDK Directory API.

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
            members = get_group_members(current_group, creds)
            # check if member is a group, otherwise they are a user
            for member in members:
                if member["type"] == "GROUP":
                    if member["email"] not in searched_groups:
                        # add current group to searched groups
                        searched_groups.append(member["email"])
                        # add group to queue
                        group_queue.append(member["email"])
                else:
                    # add user to list of group users
                    group_users.add(member["email"])

        iam_users[group] = list(group_users)

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


def get_instance_users(instance_connection_names, creds):
    """Get users that belong to each Cloud SQL instance.

    Given a list of Cloud SQL instance names and a Google Cloud project, get a list
    of database users that belong to each instance.

    Args:
        instances: List of Cloud SQL instance names.
            (e.g., ["my-project:my-region:my-instance", "my-project:my-region:my-other-instance"])
        creds: Credentials to call Cloud SQL Admin API.

    Returns:
        db_users: A dict with the instance names mapping to their list of database users.
    """
    # create dict to hold database users of each instance
    db_users = defaultdict(list)
    for connection_name in instance_connection_names:
        # extract project name and instance name from connection name
        connection_name_split = connection_name.split(":")
        project, instance = connection_name_split[0], connection_name_split[2]
        users = get_db_users(instance, project, creds)
        for user in users:
            db_users[connection_name].append(user["name"])
    return db_users


def get_db_users(instance, project, creds):
    """Get all database users of a Cloud SQL instance.

    Given a database instance and a Google Cloud project, get all the database
    users that belong to the database instance.

    Args:
        instance: A Cloud SQL instance name. (e.g. "my-instance")
        project: The Google Cloud project name that the instance is a resource of.
        creds: Credentials to call Cloud SQL Admin API.

    Returns:
        users: List of all database users that belong to the Cloud SQL instance.
    """
    # build service to call SQL Admin API
    service = build("sqladmin", "v1beta4", credentials=creds)
    results = service.users().list(project=project, instance=instance).execute()
    users = results.get("items", [])
    return users


def insert_db_user(user_email, instance_connection_name, project, creds):
    """Create DB user from IAM user.

    Given an IAM user's email, insert the IAM user as a DB user for Cloud SQL instance.

    Args:
        user_email: IAM users's email address.
        instance_connection_name: Instance connection name to insert DB user into.
        project: Project where Cloud SQL instance resides.
        creds: Credentials to call Cloud SQL Admin API.
    """
    # build service to call SQL Admin API
    service = build("sqladmin", "v1beta4", credentials=creds)
    user = {"name": user_email, "type": "CLOUD_IAM_USER"}
    # split instance connection name to get project name and instance name
    project, instance = (
        instance_connection_name.split(":")[0],
        instance_connection_name.split(":")[2],
    )
    try:
        results = (
            service.users()
            .insert(project=project, instance=instance, body=user)
            .execute()
        )
    except:
        print(f"Could not add IAM user `{user_email}` to DB Instance `{instance}`")
    return


def create_group_role(db, group):
    """Verify or create DB role.

    Given a group name, verify existance of DB role or create new DB role matching
    name of group to manage DB users.

    Args:
        db: Database connection pool instance.
        group: Name of group to be verified as role or created as new role.
    """
    with db.connect() as conn:
        stmt = sqlalchemy.text("CREATE ROLE IF NOT EXISTS :role")
        conn.execute(stmt, role=group)
    return


def grant_group_role(db, role, users):
    """Grant DB group role to DB users.

    Given a DB group role and a list of DB users, grant the DB role to each user.

    Args:
        db: Database connection pool instance.
        role: Name of DB role to grant to users.
        users: List of DB users' usernames.
    """
    with db.connect() as conn:
        stmt = sqlalchemy.text("GRANT :role TO :user")
        for user in users:
            conn.execute(stmt, role=role, user=user)
    return


def revoke_group_role(db, role, users):
    """Revoke DB group role to DB users.

    Given a DB group role and a list of DB users, revoke the DB role from each user.

    Args:
        db: Database connection pool instance.
        role: Name of DB role to revoke from users.
        users: List of DB users' usernames.
    """
    with db.connect() as conn:
        stmt = sqlalchemy.text("REVOKE :role FROM :user")
        for user in users:
            conn.execute(stmt, role=role, user=user)
    return


def find_users_missing_role(db, role, users):
    """Find DB users missing DB role.

    Given a list of DB users, and a specific DB role, find all DB users that don't have the
    role granted to them.

    Args:
        db: Database connection pool instance.
        role: Name of DB role to query each user for.
        users: List of DB users' usernames.

    Returns:
        users_missing_role: List of DB usernames for users who are missing role.
    """
    users_missing_role = []
    with db.connect() as conn:
        for user in users:
            # for mysql usernames are truncated to before '@' sign
            user = user.split("@")[0]
            # query roles granted to user
            stmt = sqlalchemy.text("SHOW GRANTS FOR :user")
            results = conn.execute(stmt, user=user).fetchall()
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
        '["group@example.com", "othergroup@example.com"]\n}\n\nYour configuration is '
        f"missing the `{var_name}` key."
    )
    return message


def missing_iam_users(iam_users, instance_users):
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
                user for user in users if user.split("@")[0] not in db_users
            ]
            if len(missing_users) > 0:
                for user in missing_users:
                    missing_db_users[instance].add(user)
    return missing_db_users


# read in config params
sql_instances, iam_groups = load_config("config.json")


@app.route("/", methods=["GET"])
def sanity_check():
    return "App is running!"


@app.route("/iam-users", methods=["GET"])
def test_get_iam_users():
    creds, project = default()
    delegated_creds = delegated_credentials(
        creds, IAM_SCOPES, os.environ["ADMIN_EMAIL"]
    )
    iam_users = get_iam_users(iam_groups, delegated_creds)
    print(f"List of all IAM Users: {iam_users}")
    return "Got all IAM Users!"


@app.route("/db-users", methods=["GET"])
def test_get_instance_users():
    creds, project = default()
    delegated_creds = delegated_credentials(creds, SQL_SCOPES)
    db_users = get_instance_users(sql_instances, project, delegated_creds)
    for key in db_users:
        print(f"DB Users for instance `{key}`: {db_users[key]}")
    return "Got DB Users!"


@app.route("/demo", methods=["GET"])
def run_demo():
    # read in config params
    sql_instances, iam_groups = load_config("config.json")

    # grab default creds from cloud run service account
    creds, project = default()
    # update default credentials with IAM SCOPE and domain delegation
    iam_creds = delegated_credentials(creds, IAM_SCOPES, "eno@enocom.io")
    # update default credentials with Cloud SQL scopes
    sql_creds = delegated_credentials(creds, SQL_SCOPES)

    # get IAM users of each IAM group
    iam_users = get_iam_users(iam_groups, iam_creds)
    for key in iam_users:
        print(f"IAM Users in Group {key}: {iam_users[key]}")

    # get all instance DB users
    instance_users = get_instance_users(sql_instances, sql_creds)
    for key in instance_users:
        print(f"DB Users in instance `{key}`: {instance_users[key]}")

    # find IAM users who are missing as DB users
    missing_users = missing_iam_users(iam_users, instance_users)
    for instance, users in missing_users.items():
        print(f"Missing IAM DB users for instance `{instance}`: {users}")
        for user in users:
            insert_db_user(user, instance, project, sql_creds)

    # for each instance add IAM group roles to manage permissions and grant roles if need be
    for instance in sql_instances:
        db = init_connection_engine(instance, sql_creds)

        for group, users in iam_users.items():
            # mysql role does not need email part
            role = group.split("@")[0]
            create_group_role(db, role)
            users_missing_role = find_users_missing_role(db, role, users)
            print(
                f"Users missing role `{role}` for instance `{instance}`: {users_missing_role}"
            )
            grant_group_role(db, role, users_missing_role)
            print(
                f"Granted the following users the role `{role}` on instance `{instance}`: {users_missing_role}"
            )

    return "IAM DB Groups Authn has run successfully!"
