from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List, Literal, Set
    from pyspark.sql import DataFrame
    from src.keeper import ArgsKeeper, SparkConfigKeeper


# package
sys.path.append(str(Path(__file__).parent.parent.parent))
from src.config import Config
from src.logger import SparkLogger
from src.environ import EnvironManager
from src.helper.exceptions import S3ServiceError


class SparkHelper:
    def __init__(self) -> None:
        self.config = Config("config.yaml")

        self.logger = SparkLogger(level=self.config.python_log_level).get_logger(
            logger_name=__name__
        )

        environ = EnvironManager()
        environ.load_environ()

        _REQUIRED_VARS = (
            "AWS_ENDPOINT_URL",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
        )

        environ.check_environ(var=_REQUIRED_VARS)  # type: ignore

        self.AWS_ENDPOINT_URL, self.AWS_ACCESS_KEY_ID, self.AWS_SECRET_ACCESS_KEY = map(
            os.getenv, _REQUIRED_VARS
        )

    def _get_s3_instance(self):
        "Gets ready-to-use boto3 connection instance for s3 service communication"

        self.logger.debug("Getting boto3 instance")

        s3 = boto3.session.Session().client(  # type: ignore
            service_name="s3",
            endpoint_url=self.AWS_ENDPOINT_URL,
            aws_access_key_id=self.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=self.AWS_SECRET_ACCESS_KEY,
        )
        self.logger.debug(f"Success. Boto3 instance: {s3}")

        return s3

    def _get_src_paths(
        self,
        event_type: Literal["message", "reaction", "subscription"],
        keeper: ArgsKeeper,
    ) -> Set[str]:
        """Get S3 paths contains dataset partitions.

        Collects paths corresponding to the passed in `keeper` object arguments and checks if each path exists on S3. Collects only existing paths.

        If no paths for given arguments kill process.

        ## Parameters
        `event_type` : Event type of partitions
        `keeper` : Dataclass-like object with Spark Job arguments

        ## Returns
        `List[str]` : List with existing partition paths on s3

        ## Examples
        >>> keeper = ArgsKeeper(date="2022-03-12", depth=10, ..., src_path="s3a://data-ice-lake-05/messager-data/analytics/geo-events")
        >>> src_paths = self._get_src_paths(event_type="message", keeper=keeper)
        >>> print(len(src_paths))
        4 # only 4 paths exists on s3
        >>> print(type(src_paths))
        <class 'list'>
        >>> for _ in src_paths: print(_) # how it looks
        "s3a://data-ice-lake-05/messager-data/analytics/geo-events/event_type=message/date=2022-03-12"
        ...
        "s3a://data-ice-lake-05/messager-data/analytics/geo-events/event_type=message/date=2022-03-11"
        """
        self.logger.debug(f"Collecting src paths for {event_type} event type")

        s3 = self._get_s3_instance()

        date = datetime.strptime(keeper.date, r"%Y-%m-%d").date()

        paths = (
            f"{keeper.src_path}/event_type={event_type}/date="
            + str(date - timedelta(days=i))
            for i in range(int(keeper.depth))
        )

        self.logger.debug("Checking if each path exists on S3")

        existing_paths = []
        for path in paths:
            self.logger.debug(f"Checking {path}")
            try:
                response = s3.list_objects(
                    Bucket=path.split(sep="/")[2],
                    MaxKeys=5,
                    Prefix="/".join(path.split(sep="/")[3:]),
                )

                if "Contents" in response.keys():
                    existing_paths.append(path)
                    self.logger.debug("OK")
                else:
                    self.logger.debug(f"No data for '{path}' path. Skipping")
                    continue

            except ClientError as e:
                raise S3ServiceError(str(e))

        # if returns empty list - exit
        if existing_paths == [] or existing_paths is None:
            raise S3ServiceError("No data on S3 for given arguments")

        self.logger.debug(f"Done. {len(existing_paths)} paths collected")

        return set(existing_paths)
