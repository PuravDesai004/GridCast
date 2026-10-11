"""USER-RUN ONLY. Imported by the manual scripts, never by GridCast local commands."""

import os


def user_session():
    from snowflake.snowpark import Session

    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_ROLE"]
    if any(not os.environ.get(key) for key in required):
        raise ValueError("set private account/user/role environment variables in your own session")
    return Session.builder.configs(
        {
            "account": os.environ["SNOWFLAKE_ACCOUNT"],
            "user": os.environ["SNOWFLAKE_USER"],
            "role": os.environ["SNOWFLAKE_ROLE"],
            "authenticator": "externalbrowser",
            "warehouse": "GRIDCAST_WH",
            "database": "GRIDCAST_PILOT",
            "schema": "FEATURES",
            "session_parameters": {
                "TIMEZONE": "UTC",
                "QUERY_TAG": "GridCast_user_python",
                "STATEMENT_TIMEOUT_IN_SECONDS": 300,
            },
        }
    ).create()
