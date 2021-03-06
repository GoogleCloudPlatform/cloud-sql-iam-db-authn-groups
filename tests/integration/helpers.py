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

from iam_groups_authn.sql_admin import InstanceConnectionName
from googleapiclient import discovery


def delete_database_user(instance_connection_name, user, credentials):
    """Helper function to delete database user of Cloud SQL instance.

    Args:
        instance_connection_name: Instance connection name of Cloud SQL instance.
            (e.g. "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>")
        user: Database user's email of user to delete.
        credentials: OAuth2 credentials for API calls.
    """

    instance = InstanceConnectionName(*instance_connection_name.split(":"))
    service = discovery.build("sqladmin", "v1beta4", credentials=credentials)
    try:
        request = (
            service.users()
            .delete(
                project=instance.project,
                instance=instance.instance,
                host="%",
                name=user,
            )
            .execute()
        )
    except Exception as e:
        raise Exception(
            f"Failed to delete database user `{user}` from instance `{instance_connection_name}`."
        ) from e


def delete_iam_member(group, member_email, credentials):
    """Helper function to delete IAM member from IAM group.

    Args:
        group: Email address of IAM group in which to delete member from.
        member_email: Email address of IAM member in which to delete.
        credentials: OAuth2 credentials for API calls.
    """
    service = discovery.build("admin", "directory_v1", credentials=credentials)
    try:
        results = (
            service.members().delete(groupKey=group, memberKey=member_email).execute()
        )
    except Exception as e:
        raise Exception(
            f"Failed to remove IAM member `{member_email}` from group `{group}`."
        ) from e


def add_iam_member(group, member_email, credentials):
    """Helper function to add IAM member from IAM group.

    Args:
        group: Email address of IAM group in which to add member from.
        member_email: Email address of IAM member in which to add.
        credentials: OAuth2 credentials for API calls.
    """
    service = discovery.build("admin", "directory_v1", credentials=credentials)
    member = {"email": member_email, "role": "MEMBER"}
    try:
        results = service.members().insert(groupKey=group, body=member).execute()
    except Exception as e:
        raise Exception(
            f"Failed to insert IAM member `{member_email}` into group `{group}`."
        ) from e
