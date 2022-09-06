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

from typing import NamedTuple
from iam_groups_authn.mysql import mysql_username
from iam_groups_authn.postgres import postgres_username


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


async def get_instance_users(user_service, instance_connection_name):
    """Get users that belong to a Cloud SQL instance.

    Given a Cloud SQL instance name and a Google Cloud project, get a list
    of database users that belong to that instance.

    Args:
        user_service: A UserService object for calling SQL admin APIs.
        instance_connection_name: Cloud SQL instance connection name.
            (e.g., "my-project:my-region:my-instance")

    Returns:
        db_users: A list with the names of database users for the given instance.
    """
    db_users = []
    # get database users for instance
    users = await user_service.get_db_users(
        InstanceConnectionName(*instance_connection_name.split(":"))
    )
    for user in users:
        db_users.append(user["name"])
    return db_users


async def add_missing_db_users(
    user_service, iam_future, db_future, instance_connection_name, database_type
):
    """Add missing IAM users as database users on instance.

    Args:
        user_service: A UserService object for calling SQL admin APIs.
        iam_future: Future for list of IAM users who are members of IAM group.
        db_future: Future for list of DB users on Cloud SQL database instance.
        instance_connection_name: Cloud SQL instance connection name.
            (e.g., "my-project:my-region:my-instance")
        database_type: Type of database for Cloud SQL instance.
    """
    iam_users, db_users = await iam_future, await db_future
    # find IAM users who are missing as DB users
    if database_type.is_mysql():
        missing_db_users = set(
            [user for user in iam_users if mysql_username(user) not in db_users]
        )
    else:
        missing_db_users = set(
            [user for user in iam_users if postgres_username(user) not in db_users]
        )
    # add missing users to database instance
    for user in missing_db_users:
        await user_service.insert_db_user(
            user,
            InstanceConnectionName(*instance_connection_name.split(":")),
            database_type,
        )
    return missing_db_users
