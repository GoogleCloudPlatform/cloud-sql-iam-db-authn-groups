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
from app import get_users_missing_role

# fake fetcher class using duck typing
class FakeFetcher:
    """Fake GrantFetcher class for testing."""

    def __init__(self, results):
        """Initalizes a FakeFetcher.

        Args:
            results: Dict with DB username as key and list of grants as values.
        """
        self.results = results

    async def fetch_user_grants(self, user):
        """Fake fetch_user_grants for testing.

        Args:
            user: DB username to get list of grants for.

        Returns:
            List of grants for the DB user `user`.
        """
        return self.results[user]


@pytest.mark.asyncio
async def test_single_user_missing_role():
    """Test for single user missing required role."""
    data = {
        "jack": [
            ("GRANT USAGE ON *.* TO `jack`@`%`"),
            ("GRANT `mygroup`@`%`,`test-group`@`%` TO `jack`@`%`"),
        ],
        "test": [("GRANT USAGE ON *.* TO `test`@`%`")],
    }
    fetcher = FakeFetcher(data)
    results = await get_users_missing_role(
        fetcher, "mygroup", ["jack@test.com", "test@test.com"]
    )
    assert results == ["test"]


@pytest.mark.asyncio
async def test_multiple_users_missing_roles():
    """Test for multiple users missing required role."""
    data = {
        "jack": [
            ("GRANT USAGE ON *.* TO `jack`@`%`"),
            ("GRANT `group`@`%`,`test-group`@`%` TO `jack`@`%`"),
        ],
        "test": [
            ("GRANT USAGE ON *.* TO `test`@`%`"),
            ("GRANT `group`@`%`,`test-group`@`%` TO `test`@`%`"),
        ],
        "user1": [("GRANT `test-group` TO `user1`@`")],
    }
    fetcher = FakeFetcher(data)
    results = await get_users_missing_role(
        fetcher, "mygroup", ["jack@test.com", "test@test.com", "user1@test.com"]
    )
    assert results == ["jack", "test", "user1"]


@pytest.mark.asyncio
async def test_no_missing_roles():
    """Test where no users are missing role.

    Should return empty list.
    """
    data = {
        "jack": [
            ("GRANT USAGE ON *.* TO `jack`@`%`"),
            ("GRANT `mygroup`@`%`,`test-group`@`%` TO `jack`@`%`"),
        ],
        "test": [
            ("GRANT USAGE ON *.* TO `test`@`%`"),
            ("GRANT `mygroup`@`%`,`test-group`@`%` TO `test`@`%`"),
        ],
        "user1": [("GRANT `test-group` TO `user1`@`")],
    }
    fetcher = FakeFetcher(data)
    results = await get_users_missing_role(
        fetcher, "test-group", ["jack@test.com", "test@test.com", "user1@test.com"]
    )
    assert results == []


@pytest.mark.asyncio
async def test_role_name_within_other_role_name():
    """Test where one role name is substring of another role name.

    Should return only single proper missing role for each user.
    """
    data = {
        "jack": [
            ("GRANT USAGE ON *.* TO `jack`@`%`"),
            ("GRANT `mygroup`@`%`,`test-group`@`%` TO `jack`@`%`"),
        ],
        "test": [
            ("GRANT USAGE ON *.* TO `test`@`%`"),
            ("GRANT `mygroup2`@`%`,`test-group`@`%` TO `test`@`%`"),
        ],
    }
    fetcher = FakeFetcher(data)
    results = await get_users_missing_role(
        fetcher, "mygroup", ["jack@test.com", "test@test.com"]
    )
    assert results == ["test"]
    results = await get_users_missing_role(
        fetcher, "mygroup2", ["jack@test.com", "test@test.com"]
    )
    assert results == ["jack"]


@pytest.mark.asyncio
async def test_empty_users():
    """Test with empty/no users passed in.

    Should return empty list.
    """
    data = {
        "jack": [
            ("GRANT USAGE ON *.* TO `jack`@`%`"),
            ("GRANT `mygroup`@`%`,`test-group`@`%` TO `jack`@`%`"),
        ],
        "test": [
            ("GRANT USAGE ON *.* TO `test`@`%`"),
            ("GRANT `mygroup`@`%`,`test-group`@`%` TO `test`@`%`"),
        ],
    }
    fetcher = FakeFetcher(data)
    results = await get_users_missing_role(fetcher, "mygroup", [])
    assert results == []
