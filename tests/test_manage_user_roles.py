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

from collections import defaultdict
import pytest
from app.sync import manage_user_roles


class FakeRoleService:
    """Fake RoleService class for testing."""

    def __init__(self, role_grants, users_with_roles):
        """Initalizes a FakeRoleService.

        Args:
            results: Dict with DB username as key and list of grants as values.
        """
        self.role_grants = role_grants
        self.users_with_roles = users_with_roles

    async def fetch_role_grants(self, group_name):
        """Fake fetch_role_grants for testing"""
        return self.role_grants.get(group_name, [])

    async def create_group_role(self, role):
        """Fake create_group_role for testing, does nothing"""
        if role not in self.users_with_roles:
            self.users_with_roles[role] = []
        return

    async def grant_group_role(self, role, users_missing_role):
        """Fake grant_group_role for testing"""
        for user in users_missing_role:
            self.users_with_roles[role].append(user)
        return

    async def revoke_group_role(self, role, users_to_revoke):
        """Fake revoke_group_role for testing"""
        for user in users_to_revoke:
            self.users_with_roles[role].remove(user)
        return


@pytest.mark.asyncio
async def test_correct_roles():
    """Test with all DB users having correct roles, happy path.

    Should return users_with_roles unchanged"""
    iam_users = {
        "iam-group": ["user@test.com", "user2@test.com"],
        "iam-group2": ["user3@test.com", "user4@test.com"],
    }
    role_grants = {
        "iam-group": [("iam-group", "user"), ("iam-group", "user2")],
        "iam-group2": [("iam-group2", "user3"), ("iam-group2", "user4")],
    }
    users_with_roles = {
        "iam-group": ["user", "user2"],
        "iam-group2": ["user3", "user4"],
    }
    role_service = FakeRoleService(role_grants, users_with_roles)
    users_with_roles = await manage_user_roles(role_service, iam_users)
    assert role_service.users_with_roles == {
        "iam-group": ["user", "user2"],
        "iam-group2": ["user3", "user4"],
    }


@pytest.mark.asyncio
async def test_grant_roles():
    """Test where IAM group members need to be granted group roles.

    Should return with users_with_roles having new IAM users with granted roles."""
    iam_users = {"iam-group": ["user@test.com", "user2@test.com"]}
    # user2 is missing the group role
    role_grants = {"iam-group": [("iam-group", "user")]}
    users_with_roles = {"iam-group": ["user"]}
    role_service = FakeRoleService(role_grants, users_with_roles)
    users_with_roles = await manage_user_roles(role_service, iam_users)
    # user2 should now have group role
    assert set(role_service.users_with_roles) == set({"iam-group": ["user", "user2"]})


@pytest.mark.asyncio
async def test_revoke_roles():
    """Test where DB Users have IAM group role but are not IAM group members.

    Should return users_with_roles having revoked group roles from DB users not in IAM group."""
    iam_users = {"iam-group": ["user@test.com"]}
    # user2 has group role but is not in IAM group
    role_grants = {"iam-group": [("iam-group", "user"), ("iam-group", "user2")]}
    users_with_roles = {"iam-group": ["user", "user2"]}
    role_service = FakeRoleService(role_grants, users_with_roles)
    users_with_roles = await manage_user_roles(role_service, iam_users)
    # user2 should have had group role revoked
    assert set(role_service.users_with_roles) == set({"iam-group": ["user"]})


@pytest.mark.asyncio
async def test_empty_role_grants():
    """Test where no IAM DB users have roles granted.

    Should return users_with_roles having granted proper group roles to all users."""
    iam_users = {"iam-group": ["user@test.com", "user2@test.com"]}
    # no roles granted, should create and grant roles to users
    role_grants = defaultdict(list)
    users_with_roles = defaultdict(list)
    role_service = FakeRoleService(role_grants, users_with_roles)
    users_with_roles = await manage_user_roles(role_service, iam_users)
    # all IAM users should have DB users with proper group roles
    assert set(role_service.users_with_roles) == set({"iam-group": ["user", "user2"]})


@pytest.mark.asyncio
async def test_grant_and_revoke():
    """Test where an IAM user switches IAM groups.

    Should return users_with_roles having granted user new role and revoked old role."""
    iam_users = {"iam-group": ["user@test.com", "user2@test.com"]}
    # user2 goes from `iam-group2` to `iam-group`
    role_grants = {
        "iam-group": [("iam-group", "user")],
        "iam-group2": [("iam-group2", "user2")],
    }
    users_with_roles = {"iam-group": ["user"], "iam-group2": ["user2"]}
    role_service = FakeRoleService(role_grants, users_with_roles)
    users_with_roles = await manage_user_roles(role_service, iam_users)
    assert set(role_service.users_with_roles) == set(
        {"iam-group": ["user", "user2"], "iam-group2": []}
    )


@pytest.mark.asyncio
async def test_create_grant_revoke():
    """Test correct management of all user permissions.

    Should return users_with_roles having created new role, granted roles and revoked roles"""
    iam_users = {
        "iam-group": ["user@test.com", "user2@test.com"],
        "iam-group2": ["user2@test.com"],
        "iam-group3": ["user3@test.com"],
    }
    # Operations:
    # - user2 needs to be granted role `iam-group`
    # - user3 needs to be revoked role `iam-group2`
    # - role created for `iam-group3` and granted to user3
    role_grants = {
        "iam-group": [("iam-group", "user")],
        "iam-group2": [("iam-group2", "user2"), ("iam-group2", "user3")],
    }
    users_with_roles = {"iam-group": ["user"], "iam-group2": ["user2", "user3"]}
    role_service = FakeRoleService(role_grants, users_with_roles)
    users_with_roles = await manage_user_roles(role_service, iam_users)
    # all IAM users should have DB users with proper group roles
    assert set(role_service.users_with_roles) == set(
        {
            "iam-group": ["user", "user2"],
            "iam-group2": ["user2"],
            "iam-group3": ["user3"],
        }
    )
