#  SPDX-License-Identifier: Apache-2.0

import os

from gyp_action_lib import Shell

opt = [] if "GITHUB_ACTIONS" in os.environ else ["-q"]

# Check if poetry.lock already exists and just touch it to avoid poetry requirement
poetry_lock_path = os.path.join(Shell.core_dir, "poetry.lock")
if os.path.exists(poetry_lock_path):
    Shell.touch("poetry.lock")
else:
    Shell.run(["yarn", "-s", "poetry", "lock"] + opt)
    Shell.run(["yarn", "-s", "poetry", "install"] + opt)
    Shell.touch("poetry.lock")
