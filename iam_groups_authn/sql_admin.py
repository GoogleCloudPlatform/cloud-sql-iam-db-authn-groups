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

# sql_admin.py contains functions for interacting with the SQL Admin API

from functools import partial
from collections import defaultdict
from quart.utils import run_sync
from typing import NamedTuple


class InstanceConnectionName(NamedTuple):
    """A class to manage instance connection names.

    Args:
        project (str): Project name that instance belongs to.
        region (str): Region where instance is located.
        instance (str): Name of instance.
    """

    project: str
    region: str
    instance: str


async def get_instance_users(user_service, instance_connection_names):
    """Get users that belong to each Cloud SQL instance.

    Given a list of Cloud SQL instance names and a Google Cloud project, get a list
    of database users that belong to each instance.

    Args:
        user_service: A UserService object for calling SQL admin APIs.
        instance_connection_names: List of Cloud SQL instance connection names.
            (e.g., ["my-project:my-region:my-instance", "my-project:my-region:my-other-instance"])

    Returns:
        db_users: A dict with the instance names mapping to their list of database users.
    """
    # create dict to hold database users of each instance
    db_users = defaultdict(list)
    for connection_name in instance_connection_names:
        get_users = partial(
            user_service.get_db_users,
            InstanceConnectionName(*connection_name.split(":")),
        )
        users = await run_sync(get_users)()
        for user in users:
            db_users[connection_name].append(user["name"])
    return db_users
