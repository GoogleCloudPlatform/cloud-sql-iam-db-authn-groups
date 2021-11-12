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
import asyncio
from iam_groups_authn.sql_admin import add_missing_db_users


class FakeUserService:
    """Fake UserService class for tests."""

    def __init__(self):
        pass

    async def insert_db_user(self, user, instance_connection_name):
        pass


@pytest.mark.asyncio
async def test_no_missing_users():
    """Test where all IAM users have corresponding database user.
    Should return empty set.
    """
    user_service = FakeUserService()
    iam_future = asyncio.Future()
    iam_future.set_result(["user1@test.com", "user2@test.com"])
    mysql_users = asyncio.Future()
    mysql_users.set_result(["user1", "user2"])
    postgres_users = asyncio.Future()
    postgres_users.set_result(["user1@test.com", "user2@test.com"])

    missing_mysql_users = await add_missing_db_users(
        user_service, iam_future, mysql_users, "group:region:instance", "mysql"
    )
    assert missing_mysql_users == set()
    missing_postgres_users = await add_missing_db_users(
        user_service, iam_future, postgres_users, "group:region:instance", "postgresql"
    )
    assert missing_postgres_users == set()


@pytest.mark.asyncio
async def test_missing__users():
    """Test where there are IAM users missing corresponding database user.
    Should return set of the emails of IAM users missing database user.
    """
    user_service = FakeUserService()
    iam_future = asyncio.Future()
    iam_future.set_result(["user1@test.com", "user2@test.com", "user3@test.com"])
    postgres_users = asyncio.Future()
    postgres_users.set_result(["user1@test.com"])
    mysql_users = asyncio.Future()
    mysql_users.set_result(["user1"])

    missing_iam_users = await add_missing_db_users(
        user_service, iam_future, postgres_users, "group:region:instance", "postgresql"
    )
    assert missing_iam_users == set(["user2@test.com", "user3@test.com"])

    missing_iam_users = await add_missing_db_users(
        user_service, iam_future, mysql_users, "group:region:instance", "mysql"
    )
    assert missing_iam_users == set(["user2@test.com", "user3@test.com"])


@pytest.mark.asyncio
async def test_no_iam_users():
    """Test where there are no IAM users.
    Should return empty set.
    """
    user_service = FakeUserService()
    iam_future = asyncio.Future()
    iam_future.set_result([])
    postgres_users = asyncio.Future()
    postgres_users.set_result(["user1@test.com"])
    mysql_users = asyncio.Future()
    mysql_users.set_result(["user1"])

    missing_iam_users = await add_missing_db_users(
        user_service, iam_future, postgres_users, "group:region:instance", "postgresql"
    )
    assert missing_iam_users == set()
    missing_iam_users = await add_missing_db_users(
        user_service, iam_future, mysql_users, "group:region:instance", "mysql"
    )
    assert missing_iam_users == set()


@pytest.mark.asyncio
async def test_no_database_users():
    """Test where there are no database users.
    Should return set of emails of all IAM users.
    """
    user_service = FakeUserService()
    iam_future = asyncio.Future()
    iam_future.set_result(["user1@test.com", "user2@test.com"])
    users = asyncio.Future()
    users.set_result([])

    missing_iam_users = await add_missing_db_users(
        user_service, iam_future, users, "group:region:instance", "postgresql"
    )
    assert missing_iam_users == set(["user1@test.com", "user2@test.com"])
    missing_iam_users = await add_missing_db_users(
        user_service, iam_future, users, "group:region:instance", "mysql"
    )
    assert missing_iam_users == set(["user1@test.com", "user2@test.com"])
