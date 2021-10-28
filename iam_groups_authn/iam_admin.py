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

# iam_admin.py contains functions for interacting with the Admin Directory API
# to access IAM groups and their users

from quart.utils import run_sync
from collections import defaultdict
from functools import partial


async def get_iam_users(user_service, group):
    """Get list of all IAM users within an IAM group.

    Given the email of an IAM group, get all IAM users that are members within
    the group or a nested child group.

    Args:
        user_service: Instance of a UserService object.
        group: Email of an IAM group. (e.g., "group@example.com")

    Returns:
        iam_users: Set containing all IAM users found within IAM group.
    """
    group_queue = [group]
    # set initial groups searched to input group
    searched_groups = group_queue.copy()
    group_users = set()
    while group_queue:
        current_group = group_queue.pop(0)
        # get all members of current IAM group
        members_partial = partial(user_service.get_group_members, current_group)
        members = await run_sync(members_partial)()
        # check if member is a group, otherwise they are a user
        for member in members:
            if member["type"] == "GROUP":
                if member["email"] not in searched_groups:
                    # add current group to searched groups
                    searched_groups.append(member["email"])
                    # add group to queue
                    group_queue.append(member["email"])
            elif member["type"] == "USER":
                # add user to list of group users
                group_users.add(member["email"])
            else:
                continue
    return group_users
