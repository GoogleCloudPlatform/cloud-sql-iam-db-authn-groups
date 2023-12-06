# Copyright 2023 Google LLC
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

from iam_groups_authn.utils import strip_minor_version

test_data = [
    ("MYSQL_8_0", "MYSQL_8_0"),
    ("MYSQL_8_0_26", "MYSQL_8_0"),
    ("MYSQL_8_0_35", "MYSQL_8_0"),
    ("POSTGRES_15", "POSTGRES_15"),
    ("POSTGRES_14", "POSTGRES_14"),
    ("POSTGRES_13", "POSTGRES_13"),
    ("POSTGRES_12", "POSTGRES_12"),
    ("POSTGRES_11", "POSTGRES_11"),
    ("POSTGRES_10", "POSTGRES_10"),
    ("POSTGRES_9_6", "POSTGRES_9_6"),
    ("POSTGRES_9_6", "POSTGRES_9_6"),
]

@pytest.mark.parametrize("database_version,expected", test_data)
def test_strip_minor_version(database_version, expected):
    """
    Test that strip_minor_version() works correctly.
    """
    database_version = strip_minor_version(database_version)
    assert database_version == expected
