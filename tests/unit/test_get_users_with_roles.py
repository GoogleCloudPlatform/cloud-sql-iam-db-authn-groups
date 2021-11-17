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
from iam_groups_authn.sync import get_users_with_roles
from collections import defaultdict

# fake fetcher class using duck typing
class FakeRoleService:
    """Fake RoleService class for testing"""

    def __init__(self, results):
        """Initializes a FakeRoleService

        Args:
            results: List with tuples in form (FROM_USER, TO_USER) showing grants.
        """
        self.results = results

    async def fetch_role_grants(self, group_name):
        """Fake fetch_role_grants for testing"""
        return self.results[group_name]


@pytest.mark.asyncio
async def test_single_group_role():
    """Test with single group role for happy path when multiples users are granted group role."""
    data = {"group": [("group", "user"), ("group", "user2"), ("group", "user3")]}
    role_service = FakeRoleService(data)
    users_with_roles = await get_users_with_roles(role_service, "group")
    assert users_with_roles == ["user", "user2", "user3"]


@pytest.mark.asyncio
async def test_multiple_group_roles():
    """Test with multiple group roles for happy path when multiples users are granted group role."""
    data = {
        "group": [("group", "user"), ("group", "user2")],
        "group2": [("group2", "user3"), ("group2", "user4")],
    }
    role_service = FakeRoleService(data)
    users_with_roles = await get_users_with_roles(role_service, "group")
    assert users_with_roles == ["user", "user2"]

    users_with_roles = await get_users_with_roles(role_service, "group2")
    assert users_with_roles == ["user3", "user4"]


@pytest.mark.asyncio
async def test_no_users_with_roles():
    """Test with no users that have group roles granted to them.

    Should return empty defaultdict of type list"""
    data = defaultdict(list)
    role_service = FakeRoleService(data)
    users_with_roles = await get_users_with_roles(role_service, "group")
    assert users_with_roles == []


@pytest.mark.asyncio
async def test_no_users_for_one_role():
    """Test multiple group roles where one role has no users with the grant.

    Should return only the roles with users that have grants"""
    data = {
        "group": [("group", "user"), ("group", "user2")],
        "group2": [("group2", "user3"), ("group2", "user4")],
        "group3": [],
    }
    role_service = FakeRoleService(data)
    users_with_roles = await get_users_with_roles(role_service, "group")
    assert users_with_roles == ["user", "user2"]

    users_with_roles = await get_users_with_roles(role_service, "group2")
    assert users_with_roles == ["user3", "user4"]

    users_with_roles = await get_users_with_roles(role_service, "group3")
    assert users_with_roles == []
