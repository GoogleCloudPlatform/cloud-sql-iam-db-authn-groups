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

from quart.utils import run_sync
from collections import defaultdict
from functools import partial


async def get_iam_users(user_service, groups):
    """Get list of all IAM users within IAM groups.

    Given a list of IAM groups, get all IAM users that are members within one or
    more of the groups or a nested child group.

    Args:
        user_service: Instance of a UserService object.
        groups: List of IAM groups. (e.g., ["group@example.com", "abc@example.com"])

    Returns:
        iam_users: Set containing all IAM users found within IAM groups.
    """
    # keep track of iam users using set for no duplicates
    iam_users = defaultdict(list)
    # loop through groups and get their IAM users
    for group in groups:
        group_queue = [group]
        # set initial groups searched to input groups
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
        # only add to dict if group has members, allows skipping of not valid groups
        if group_users:
            iam_users[group] = group_users

    return iam_users
