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

import pytest
import os
from google.auth import default
from google.auth.transport.requests import Request
import sqlalchemy
from aiohttp import ClientSession
from helpers import delete_database_user, delete_iam_member, add_iam_member
from iam_groups_authn.iam_admin import get_iam_users
from iam_groups_authn.mysql import mysql_username
from iam_groups_authn.postgres import init_postgres_connection_engine
from iam_groups_authn.sql_admin import get_instance_users
from iam_groups_authn.sync import groups_sync, UserService
import time

# load test params from environment
sql_instance = os.environ["POSTGRES_INSTANCE"]
iam_groups = [os.environ["IAM_GROUPS"]]
test_user = os.environ["TEST_USER"]

scopes = [
    "https://www.googleapis.com/auth/admin.directory.group.member",
    "https://www.googleapis.com/auth/sqlservice.admin",
]


def check_role_postgres(db, role):
    """Function to get database users who have given PostgreSQL role.

    Args:
        db: Database connection pool to connect to.
        role: Given role to query users in database with.

    Returns:
        users_with_role: List of users who have role granted to them.
    """

    stmt = sqlalchemy.text(
        "SELECT (SELECT pg_roles.rolname FROM pg_roles WHERE oid = pg_auth_members.member) FROM pg_roles, pg_auth_members WHERE pg_auth_members.roleid = (SELECT oid FROM pg_roles WHERE rolname= :role) and pg_roles.rolname= :role"
    )
    with db.connect() as conn:
        results = conn.execute(stmt, {"role": role}).fetchall()
    users_with_role = [result[0] for result in results]
    return users_with_role


@pytest.fixture(name="credentials", autouse=True)
def setup_and_teardown():
    """Function for setting up and tearing down test."""

    # load in service account credentials for test
    credentials, project = default(scopes=scopes)

    # check if credentials are expired
    if not credentials.valid:
        request = Request()
        credentials.refresh(request)

    yield credentials

    try:
        # cleanup user from database
        delete_database_user(sql_instance, test_user, credentials)
        # re-add member to IAM group
        add_iam_member(iam_groups[0], test_user, credentials)
        # wait 30 seconds, adding IAM member is slow
        time.sleep(30)
    except Exception:
        print("------------------------Cleanup Failed!------------------------")


@pytest.mark.asyncio
async def test_service_postgres(credentials):
    """Test end-to-end usage of GroupSync service on PostgreSQL instance.

    Test plan:
        - Verifies test user is not a database user
        - Run GroupSync
        - Verifies test user is now a database user
        - Verifies all IAM members of IAM group have been granted group role
        - Remove test user from IAM group
        - Run GroupSync
        - Verifies test user no longer has group role
    """

    # remove database user if they exist
    try:
        delete_database_user(sql_instance, test_user, credentials)
    except Exception:
        print("Database user must already have been deleted!")

    # create aiohttp client session for async API calls
    client_session = ClientSession(headers={"Content-Type": "application/json"})

    # check that test_user is not a database user
    user_service = UserService(client_session, credentials)
    db_users = await get_instance_users(user_service, sql_instance)
    assert test_user not in db_users

    # make sure test_user is member of IAM group
    try:
        add_iam_member(iam_groups[0], test_user, credentials)
        # wait 30 seconds, adding IAM member is slow
        time.sleep(30)
    except Exception:
        print("Member must already belong to IAM Group.")

    # run groups sync
    await groups_sync(iam_groups, [sql_instance], credentials, False)

    # check that test_user has been created as database user
    db_users = await get_instance_users(user_service, sql_instance)
    assert test_user in db_users

    # create database connection to instance
    pool = init_postgres_connection_engine(sql_instance, credentials)

    # check that each iam group member has group role
    for iam_group in iam_groups:
        users_with_role = check_role_postgres(pool, mysql_username(iam_group))
        iam_members = await get_iam_users(user_service, iam_group)
        for member in iam_members:
            assert member in users_with_role

    # remove test_user from IAM group
    delete_iam_member(iam_groups[0], test_user, credentials)

    # wait 30 seconds, deleting IAM member is slow
    time.sleep(30)

    # run groups sync
    await groups_sync(iam_groups, [sql_instance], credentials, False)

    # verify test_user no longer has group role
    users_with_role = check_role_postgres(pool, mysql_username(iam_groups[0]))
    assert test_user not in users_with_role

    # close aiohttp client session for graceful exit
    if not client_session.closed:
        await client_session.close()
