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

# utils.py contains utility functions shared between modules

import asyncio
from functools import partial, wraps
from enum import Enum


def async_wrap(func):
    """Wrapper function to turn synchronous functions into async functions.

    Args:
        func: Synchronous function to wrap.
    """

    @wraps(func)
    async def run(*args, loop=None, executor=None, **kwargs):
        if loop is None:
            loop = asyncio.get_event_loop()
        pfunc = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, pfunc)

    return run


class DatabaseVersion(Enum):
    """Enum class for database version."""

    MYSQL_8_0 = "mysql"
    POSTGRES_13 = "postgresql"
    POSTGRES_12 = "postgresql"
    POSTGRES_11 = "postgresql"
    POSTGRES_10 = "postgresql"
    POSTGRES_9_6 = "postgresql"


class RoleService:
    """Interface for managing a database and it's group roles."""

    def __init__(self, db):
        pass

    def fetch_role_grants(self, group_name):
        pass

    def create_group_role(self, role):
        pass

    def grant_group_role(self, role, users):
        pass

    def revoke_group_role(self, role, users):
        pass
