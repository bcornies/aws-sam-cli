import selectors
import shutil
import signal
import uuid
from typing import Optional, Dict, List
from unittest import TestCase, skipIf
import threading
from subprocess import Popen, PIPE
import time
import os
import random
from pathlib import Path

import docker

from tests.testing_utils import SKIP_DOCKER_TESTS, SKIP_DOCKER_MESSAGE, run_command


@skipIf(SKIP_DOCKER_TESTS, SKIP_DOCKER_MESSAGE)
class StartLambdaIntegBaseClass(TestCase):
    template: Optional[str] = None
    container_mode: Optional[str] = None
    parameter_overrides: Optional[Dict[str, str]] = None
    binary_data_file: Optional[str] = None
    integration_dir = str(Path(__file__).resolve().parents[2])
    invoke_image: Optional[List] = None

    build_before_invoke = False
    build_overrides: Optional[Dict[str, str]] = None

    @classmethod
    def setUpClass(cls):
        # This is the directory for tests/integration which will be used to file the testdata
        # files for integ tests
        cls.template = cls.integration_dir + cls.template_path
        cls.port = str(StartLambdaIntegBaseClass.random_port())
        cls.env_var_path = cls.integration_dir + "/testdata/invoke/vars.json"

        if cls.build_before_invoke:
            cls.build()

        # remove all containers if there
        cls.docker_client = docker.from_env()
        for container in cls.docker_client.api.containers():
            cls.docker_client.api.remove_container(container, force=True)

        cls.thread = threading.Thread(target=cls.start_lambda())
        cls.thread.setDaemon(True)
        cls.thread.start()

    @classmethod
    def build(cls):
        command = "sam"
        if os.getenv("SAM_CLI_DEV"):
            command = "samdev"
        command_list = [command, "build"]
        if cls.build_overrides:
            overrides_arg = " ".join(
                ["ParameterKey={},ParameterValue={}".format(key, value) for key, value in cls.build_overrides.items()]
            )
            command_list += ["--parameter-overrides", overrides_arg]
        working_dir = str(Path(cls.template).resolve().parents[0])
        run_command(command_list, cwd=working_dir)

    @classmethod
    def start_lambda(cls, wait_time=5):
        command = "sam"
        if os.getenv("SAM_CLI_DEV"):
            command = "samdev"

        command_list = [
            command,
            "local",
            "start-lambda",
            "-t",
            cls.template,
            "-p",
            cls.port,
            "--env-vars",
            cls.env_var_path,
        ]
        if cls.container_mode:
            command_list += ["--warm-containers", cls.container_mode]

        if cls.parameter_overrides:
            command_list += ["--parameter-overrides", cls._make_parameter_override_arg(cls.parameter_overrides)]

        if cls.invoke_image:
            for image in cls.invoke_image:
                command_list += ["--invoke-image", image]

        cls.start_lambda_process = Popen(command_list, stderr=PIPE)

        while True:
            line = cls.start_lambda_process.stderr.readline()
            if "(Press CTRL+C to quit)" in str(line):
                break

        cls.stop_reading_thread = False

        def read_sub_process_stderr():
            while not cls.stop_reading_thread:
                cls.start_lambda_process.stderr.readline()

        cls.read_threading = threading.Thread(target=read_sub_process_stderr)
        cls.read_threading.start()

    @classmethod
    def _make_parameter_override_arg(self, overrides):
        return " ".join(["ParameterKey={},ParameterValue={}".format(key, value) for key, value in overrides.items()])

    @classmethod
    def tearDownClass(cls):
        # After all the tests run, we need to kill the start_lambda process.
        cls.start_lambda_process.kill()
        cls.stop_reading_thread = True

    @staticmethod
    def random_port():
        return random.randint(30000, 40000)


class WatchWarmContainersIntegBaseClass(StartLambdaIntegBaseClass):
    temp_path: Optional[str] = None
    template_path: Optional[str] = None
    code_path: Optional[str] = None
    docker_file_path: Optional[str] = None

    @classmethod
    def setUpClass(cls):
        cls.temp_path = str(uuid.uuid4()).replace("-", "")[:10]
        working_dir = str(Path(cls.integration_dir).resolve().joinpath(cls.temp_path))
        if Path(working_dir).resolve().exists():
            shutil.rmtree(working_dir)
        os.mkdir(working_dir)
        os.mkdir(Path(cls.integration_dir).resolve().joinpath(cls.temp_path).joinpath("dir"))
        cls.template_path = f"/{cls.temp_path}/template.yaml"
        cls.code_path = f"/{cls.temp_path}/main.py"
        cls.code_path2 = f"/{cls.temp_path}/dir/main2.py"
        cls.docker_file_path = f"/{cls.temp_path}/Dockerfile"
        cls.docker_file_path2 = f"/{cls.temp_path}/Dockerfile2"

        if cls.template_content:
            cls._write_file_content(cls.template_path, cls.template_content)

        if cls.code_content:
            cls._write_file_content(cls.code_path, cls.code_content)

        if cls.docker_file_content:
            cls._write_file_content(cls.docker_file_path, cls.docker_file_content)

        super().setUpClass()

    @classmethod
    def _write_file_content(cls, path, content):
        with open(cls.integration_dir + path, "w") as f:
            f.write(content)

    @classmethod
    def tearDownClass(cls):
        working_dir = str(Path(cls.integration_dir).resolve().joinpath(cls.temp_path))
        if Path(working_dir).resolve().exists():
            shutil.rmtree(working_dir)
        super().tearDownClass()
