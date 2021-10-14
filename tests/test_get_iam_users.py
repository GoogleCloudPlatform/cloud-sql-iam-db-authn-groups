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

from app import get_iam_users


class FakeUserService:
    """Fake UserService class for testing."""

    def __init__(self, members):
        """Initializes a FakeUserService.

        Args:
            group_members: Dict with group name as key and list of group's members as values.
        """
        self.members = members

    def get_group_members(self, group):
        """Fake get_group_members for testing.

        Args:
            group (str): Group name

        Returns:
            List of `group`s members.
        """
        return self.members[group]


def test_single_group():
    """Test for happy path of single IAM group when all members are type USER."""
    data = {
        "test-group@test.com": [
            {"type": "USER", "email": "test@test.com"},
            {"type": "USER", "email": "user@test.com"},
            {"type": "USER", "email": "john@abc.com"},
        ]
    }
    fake_service = FakeUserService(data)
    iam_users = get_iam_users(fake_service, groups=["test-group@test.com"])
    assert iam_users == {
        "test-group@test.com": set(("test@test.com", "user@test.com", "john@abc.com"))
    }


def test_multiple_groups():
    """Test happy path for multiple IAM groups.

    Should retunr all members of type `USER` and skip the one `CUSTOMER`.
    """
    data = {
        "test-group@test.com": [
            {"type": "USER", "email": "test@test.com"},
            {"type": "USER", "email": "user@test.com"},
            {"type": "USER", "email": "john@abc.com"},
        ],
        "test-group2@abc.com": [
            {"type": "USER", "email": "jack@test.com"},
            {"type": "USER", "email": "jane@xyz.com"},
            {"type": "CUSTOMER", "id": "123456789"},
        ],
    }
    fake_service = FakeUserService(data)
    iam_users = get_iam_users(
        fake_service, groups=["test-group@test.com", "test-group2@abc.com"]
    )
    assert iam_users == {
        "test-group@test.com": set(("test@test.com", "user@test.com", "john@abc.com")),
        "test-group2@abc.com": set(("jack@test.com", "jane@xyz.com")),
    }


def test_group_within_group():
    """Test for one group, where the group has a nested group within.

    Should return the users of both the main group and the nested group as members of the main group.
    """
    data = {
        "test-group2@abc.com": [
            {"type": "USER", "email": "jack@test.com"},
            {"type": "USER", "email": "jane@xyz.com"},
        ],
        "test-group3@xyz.com": [
            {"type": "USER", "email": "test@test.com"},
            {"type": "GROUP", "email": "test-group2@abc.com"},
        ],
    }
    fake_service = FakeUserService(data)
    iam_users = get_iam_users(fake_service, groups=["test-group3@xyz.com"])
    assert iam_users == {
        "test-group3@xyz.com": set(("test@test.com", "jack@test.com", "jane@xyz.com"))
    }


def test_empty_group():
    """Test for group with no users.

    Should return empty dict as it will skip group with no users.
    """
    data = {
        "empty-group@test.com": [],
    }
    fake_service = FakeUserService(data)
    iam_users = get_iam_users(fake_service, groups=["empty-group@test.com"])
    assert iam_users == {}


def test_customer_group():
    """Test for group with no members of type `USER` and all type `CUSTOMER`.

    Should return empty dict as it will skip all members of type `CUSTOMER`.
    """
    data = {
        "customer-group@test.com": [
            {"type": "CUSTOMER", "id": 12456789},
            {"type": "CUSTOMER", "id": 98765432},
        ],
    }
    fake_service = FakeUserService(data)
    iam_users = get_iam_users(fake_service, groups=["customer-group@test.com"])
    assert iam_users == {}


def test_group_loop():
    """Test group that has infinite loop of nested groups.

    Should return members of the main group and nested group without duplications.
    """
    data = {
        "test-group2@abc.com": [
            {"type": "USER", "email": "jack@test.com"},
            {"type": "USER", "email": "jane@xyz.com"},
            {"type": "GROUP", "email": "test-group3@xyz.com"},
        ],
        "test-group3@xyz.com": [
            {"type": "USER", "email": "test@test.com"},
            {"type": "GROUP", "email": "test-group2@abc.com"},
        ],
    }
    fake_service = FakeUserService(data)
    iam_users = get_iam_users(fake_service, groups=["test-group3@xyz.com"])
    assert iam_users == {
        "test-group3@xyz.com": set(("test@test.com", "jack@test.com", "jane@xyz.com"))
    }
