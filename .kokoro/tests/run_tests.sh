#! /bin/bash
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

# `-e` enables the script to automatically fail when a command fails
set -e

# Kokoro setup
if [ -n "$KOKORO_GFILE_DIR" ]; then
  # source secrets
  source "${KOKORO_GFILE_DIR}/secret_manager/groupsync-env-vars"
  export GOOGLE_APPLICATION_CREDENTIALS="${KOKORO_GFILE_DIR}/secret_manager/groupsync-key"

  # Move into project directory
  cd github/cloud-sql-iam-db-authn-groups
fi

# add user's pip binary path to PATH
export PATH="${HOME}/.local/bin:${PATH}"

# pip install test requirements
python3 -m pip install -r requirements-test.txt

echo -e "******************** Running tests... ********************\n"
python3 -m pytest tests/integration
echo -e "******************** Tests complete.  ********************\n"
