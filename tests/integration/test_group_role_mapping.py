# Copyright 2022 Google LLC
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

import pytest
import os
from google.auth import default
from google.auth.transport.requests import Request
import sqlalchemy
from aiohttp import ClientSession
from helpers import delete_database_user
from iam_groups_authn.mysql import init_mysql_connection_engine, mysql_username
from iam_groups_authn.sql_admin import get_instance_users
from iam_groups_authn.sync import GroupRoleMaxLengthError, groups_sync, UserService

# load test params from environment
sql_instance = os.environ["MYSQL_INSTANCE"]
long_iam_group = [os.environ["LONG_GROUP_EMAIL"]]
test_user = os.environ["TEST_USER"]

scopes = [
    "https://www.googleapis.com/auth/admin.directory.group.member",
    "https://www.googleapis.com/auth/sqlservice.admin",
]


def check_role_mysql(db, role):
    """Function to get database users who have given MySQL role.

    Args:
        db: Database connection pool to connect to.
        role: Given role to query users in database with.

    Returns:
        users_with_role: List of users who have role granted to them.
    """

    stmt = sqlalchemy.text(
        "SELECT TO_USER FROM mysql.role_edges WHERE FROM_USER= :role"
    )
    with db.connect() as conn:
        results = conn.execute(stmt, {"role": role}).fetchall()
    users_with_role = [result[0] for result in results]
    return users_with_role


@pytest.fixture(name="credentials", autouse=True)
def setup_and_teardown():
    """Function for setting up and tearing down test."""

    # load in service account credentials for test
    credentials, _ = default(scopes=scopes)

    # check if credentials are expired
    if not credentials.valid:
        request = Request()
        credentials.refresh(request)

    yield credentials

    try:
        # cleanup group role from database
        delete_database_user(sql_instance, "short-group-role", credentials)
    except Exception:
        print("------------------------Cleanup Failed!------------------------")


@pytest.mark.asyncio
async def test_long_iam_group_email_without_mapping(credentials):
    """Test IAM group email that exceeds character limit, should throw custom error.

    Test plan:
        - Run GroupSync with long IAM email (error)
        - Verify group role is not a database user
    """
    # create aiohttp client session for async API calls
    client_session = ClientSession(headers={"Content-Type": "application/json"})

    # check that group role is not a database user
    user_service = UserService(client_session, credentials)
    db_users = await get_instance_users(user_service, sql_instance)
    assert mysql_username(long_iam_group[0]) not in db_users

    # run groups_sync with email exceeding char limit
    with pytest.raises(GroupRoleMaxLengthError):
        await groups_sync(long_iam_group, [sql_instance], credentials, dict(), False)

    # check that group role has not been created as database user
    db_users = await get_instance_users(user_service, sql_instance)
    assert mysql_username(long_iam_group[0]) not in db_users

    # close aiohttp client session for graceful exit
    if not client_session.closed:
        await client_session.close()


@pytest.mark.asyncio
async def test_long_iam_group_email_with_mapping(credentials):
    """Test IAM group email that exceeds character limit with
    group_roles mapping, should succeed.

    Test plan:
        - Verify group role is not a database user
        - Run GroupSync with long IAM email and group_roles mapping
        - Verify mapped group role is a database user
        - Verify test user has been granted mapped group role
    """
    # remove mapped group role if it already exists
    try:
        delete_database_user(sql_instance, "short-group-role", credentials)
    except Exception:
        print("Database user must already have been deleted!")

    # create aiohttp client session for async API calls
    client_session = ClientSession(headers={"Content-Type": "application/json"})

    # check that mapped group role is not a database user
    user_service = UserService(client_session, credentials)
    db_users = await get_instance_users(user_service, sql_instance)
    assert "short-group-role" not in db_users

    # run groups_sync with group role mapping
    group_roles = {long_iam_group[0]: "short-group-role"}
    await groups_sync(long_iam_group, [sql_instance], credentials, group_roles, False)

    # check that group role has been created as database user
    db_users = await get_instance_users(user_service, sql_instance)
    assert "short-group-role" in db_users

    # create database connection to instance
    pool = init_mysql_connection_engine(sql_instance, credentials)

    # check that test user has group role
    users_with_role = check_role_mysql(pool, "short-group-role")
    assert mysql_username(test_user) in users_with_role

    # close aiohttp client session for graceful exit
    if not client_session.closed:
        await client_session.close()
