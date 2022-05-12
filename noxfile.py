from __future__ import absolute_import
import os
import nox

BLACK_PATHS = ["iam_groups_authn"]

if os.path.exists("samples"):
    BLACK_PATHS.append("samples")


@nox.session
def lint(session):
    """Run linters.
    Returns a failure if the linters find linting errors or sufficiently
    serious code quality issues.
    """
    session.install("-r", "requirements-test.txt")
    session.install("-r", "requirements.txt")
    session.run("black", "--check", *BLACK_PATHS)
