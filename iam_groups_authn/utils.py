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
from abc import ABC, abstractmethod


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
    """Enum class for database version.

    All supported database versions for service."""

    MYSQL_8_0 = "MYSQL_8_0"
    POSTGRES_14 = "POSTGRES_14"
    POSTGRES_13 = "POSTGRES_13"
    POSTGRES_12 = "POSTGRES_12"
    POSTGRES_11 = "POSTGRES_11"
    POSTGRES_10 = "POSTGRES_10"
    POSTGRES_9_6 = "POSTGRES_9_6"

    def is_mysql(self):
        """Helper method to determine if database is MySQL dialect."""

        return self.value.startswith("MYSQL")

    def is_postgres(self):
        """Helper method to determine if database is PostgreSQL dialect."""

        return self.value.startswith("POSTGRES")


class RoleService(ABC):
    """Interface for managing a database and it's group roles.

    This interface lays out the required methods for subclasses to implement.
    Ex. MysqlRoleService subclass would implement the methods below for MySQL."""

    @abstractmethod
    def __init__(self, db):
        pass

    @abstractmethod
    def fetch_role_grants(self, group_name):
        pass

    @abstractmethod
    def create_group_role(self, role):
        pass

    @abstractmethod
    def grant_group_role(self, role, users):
        pass

    @abstractmethod
    def revoke_group_role(self, role, users):
        pass
