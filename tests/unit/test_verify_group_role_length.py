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

from iam_groups_authn.sync import verify_group_role_length, GroupRoleMaxLengthError
from iam_groups_authn.utils import DatabaseVersion


@pytest.fixture
def iam_groups() -> list:
    return ["super-super-duper-duper-long-email@test.com"]


@pytest.fixture
def database_version() -> DatabaseVersion:
    return DatabaseVersion.MYSQL_8_0


def test_group_email_exceeds_limit(
    iam_groups: list, database_version: DatabaseVersion
) -> None:
    """Test that long IAM group email without group role param set throws error."""
    group_roles = dict()
    # test mysql (exceeds 32 chars)
    with pytest.raises(GroupRoleMaxLengthError):
        verify_group_role_length(iam_groups, group_roles, database_version)
    # test postgres (exceed 63 chars)
    postgres_groups = [
        "super-super-super-super-super-duper-duper-duper-duper-duper-long-email@test.com"
    ]
    database_version = DatabaseVersion.POSTGRES_13
    with pytest.raises(GroupRoleMaxLengthError):
        verify_group_role_length(postgres_groups, group_roles, database_version)


def test_custom_group_role_mapping(
    iam_groups: list, database_version: DatabaseVersion
) -> None:
    """Test that long IAM group email with group role mapping is successful."""
    # add short group name to show that only role mappings for long emails are required
    iam_groups.append("short-group@test.com")
    group_roles = {"super-super-duper-duper-long-email@test.com": "custom-group-role"}
    verify_group_role_length(iam_groups, group_roles, database_version)


def test_custom_group_role_mapping_exceeds_limit(
    iam_groups: list, database_version: DatabaseVersion
) -> None:
    """Test that group role mapping that exceeds limit throws error."""
    group_roles = {
        "super-super-duper-duper-long-email@test.com": "super-super-duper-duper-long-role"
    }
    with pytest.raises(GroupRoleMaxLengthError):
        verify_group_role_length(iam_groups, group_roles, database_version)
