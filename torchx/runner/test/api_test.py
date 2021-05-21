#!/usr/bin/env python3
# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pyre_extensions import none_throws
from torchx.runner import Runner
from torchx.schedulers.api import DescribeAppResponse
from torchx.schedulers.local_scheduler import LocalScheduler
from torchx.schedulers.test.test_util import write_shell_script
from torchx.specs.api import (
    Application,
    AppState,
    Container,
    Resource,
    Role,
    RunConfig,
    UnknownAppException,
)


class resource:
    SMALL = Resource(cpu=1, gpu=0, memMB=1024)
    MEDIUM = Resource(cpu=4, gpu=0, memMB=(4 * 1024))
    LARGE = Resource(cpu=16, gpu=0, memMB=(16 * 1024))


SESSION_NAME = "test_session"


@patch("torchx.runner.api.log_event")
class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp("RunnerTest")

        write_shell_script(self.test_dir, "touch.sh", ["touch $1"])
        write_shell_script(self.test_dir, "fail.sh", ["exit 1"])
        write_shell_script(self.test_dir, "sleep.sh", ["sleep $1"])

        self.scheduler = LocalScheduler(SESSION_NAME)
        self.cfg = RunConfig({"image_fetcher": "dir"})

        # resource ignored for local scheduler; adding as an example
        self.test_container = Container(image=self.test_dir).require(resource.SMALL)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir)

    def test_validate_no_roles(self, _) -> None:
        runner = Runner("test", schedulers={"default": self.scheduler})
        with self.assertRaises(ValueError):
            app = Application("no roles")
            runner.run(app)

    def test_validate_no_container(self, _) -> None:
        runner = Runner("test", schedulers={"default": self.scheduler})
        with self.assertRaises(ValueError):
            role = Role("no container").runs("echo", "hello_world")
            app = Application("no container").of(role)
            runner.run(app)

    def test_validate_invalid_replicas(self, _) -> None:
        runner = Runner("test", schedulers={"default": self.scheduler})
        with self.assertRaises(ValueError):
            container = Container("torch").require(Resource(cpu=1, gpu=0, memMB=500))
            role = (
                Role("no container")
                .runs("echo", "hello_world")
                .on(container)
                .replicas(0)
            )
            app = Application("no container").of(role)
            runner.run(app)

    def test_run(self, _) -> None:
        test_file = os.path.join(self.test_dir, "test_file")
        session = Runner(
            name=SESSION_NAME,
            schedulers={"default": self.scheduler},
            wait_interval=1,
        )
        self.assertEqual(1, len(session.scheduler_backends()))

        role = Role(name="touch").runs("touch.sh", test_file).on(self.test_container)
        app = Application("name").of(role)

        app_handle = session.run(app, cfg=self.cfg)
        app_status = none_throws(session.wait(app_handle))
        self.assertEqual(AppState.SUCCEEDED, app_status.state)

    def test_dryrun(self, _) -> None:
        scheduler_mock = MagicMock()
        session = Runner(
            name=SESSION_NAME, schedulers={"default": scheduler_mock}, wait_interval=1
        )
        role = Role(name="touch").runs("echo", "hello world").on(self.test_container)
        app = Application("name").of(role)
        session.dryrun(app, "default", cfg=self.cfg)
        scheduler_mock.submit_dryrun.assert_called_once_with(app, self.cfg)
        scheduler_mock._validate.assert_called_once()

    def test_describe(self, _) -> None:
        session = Runner(name=SESSION_NAME, schedulers={"default": self.scheduler})
        role = Role(name="sleep").runs("sleep.sh", "60").on(self.test_container)
        app = Application("sleeper").of(role)

        app_handle = session.run(app, cfg=self.cfg)
        self.assertEqual(app, session.describe(app_handle))
        # unknown app should return None
        self.assertIsNone(session.describe("default://session1/unknown_app"))

    def test_list(self, _) -> None:
        session = Runner(
            name=SESSION_NAME, schedulers={"default": self.scheduler}, wait_interval=1
        )
        role = Role(name="touch").runs("sleep.sh", "1").on(self.test_container)
        app = Application("sleeper").of(role)

        num_apps = 4

        for _ in range(num_apps):
            # since this test validates the list() API,
            # we do not wait for the apps to finish so run the apps
            # in managed mode so that the local scheduler reaps the apps on exit
            session.run(app)

        apps = session.list()
        self.assertEqual(num_apps, len(apps))

    def test_evict_non_existent_app(self, _) -> None:
        # tests that apps previously run with this session that are finished and eventually
        # removed by the scheduler also get removed from the session after a status() API has been
        # called on the app

        scheduler = LocalScheduler(session_name=SESSION_NAME, cache_size=1)
        session = Runner(
            name=SESSION_NAME, schedulers={"default": scheduler}, wait_interval=1
        )
        test_file = os.path.join(self.test_dir, "test_file")
        role = Role(name="touch").runs("touch.sh", test_file).on(self.test_container)
        app = Application("touch_test_file").of(role)

        # local scheduler was setup with a cache size of 1
        # run the same app twice (the first will be removed from the scheduler's cache)
        # then validate that the first one will drop from the session's app cache as well
        app_id1 = session.run(app, cfg=self.cfg)
        session.wait(app_id1)

        app_id2 = session.run(app, cfg=self.cfg)
        session.wait(app_id2)

        apps = session.list()

        self.assertEqual(1, len(apps))
        self.assertFalse(app_id1 in apps)
        self.assertTrue(app_id2 in apps)

    def test_status(self, _) -> None:
        session = Runner(
            name=SESSION_NAME, schedulers={"default": self.scheduler}, wait_interval=1
        )
        role = Role(name="sleep").runs("sleep.sh", "60").on(self.test_container)
        app = Application("sleeper").of(role)
        app_handle = session.run(app, cfg=self.cfg)
        app_status = none_throws(session.status(app_handle))
        self.assertEqual(AppState.RUNNING, app_status.state)
        session.stop(app_handle)
        app_status = none_throws(session.status(app_handle))
        self.assertEqual(AppState.CANCELLED, app_status.state)

    def test_status_unknown_app(self, _) -> None:
        session = Runner(
            name=SESSION_NAME, schedulers={"default": self.scheduler}, wait_interval=1
        )
        self.assertIsNone(session.status("default://test_session/unknown_app_id"))

    @patch("json.dumps")
    def test_status_ui_url(self, json_dumps_mock: MagicMock, _) -> None:
        app_id = "test_app"
        json_dumps_mock.return_value = "{}"
        mock_scheduler = MagicMock()
        resp = DescribeAppResponse()
        resp.ui_url = "https://foobar"
        mock_scheduler.submit.return_value = app_id
        mock_scheduler.describe.return_value = resp

        session = Runner(
            name="test_ui_url_session", schedulers={"default": mock_scheduler}
        )
        role = Role("ignored").runs("/bin/echo").on(self.test_container)
        app_handle = session.run(Application(app_id).of(role))
        status = none_throws(session.status(app_handle))
        self.assertEquals(resp.ui_url, status.ui_url)

    @patch("json.dumps")
    def test_status_structured_msg(self, json_dumps_mock: MagicMock, _) -> None:
        app_id = "test_app"
        json_dumps_mock.return_value = "{}"
        mock_scheduler = MagicMock()
        resp = DescribeAppResponse()
        resp.structured_error_msg = '{"message": "test error"}'
        mock_scheduler.submit.return_value = app_id
        mock_scheduler.describe.return_value = resp

        session = Runner(
            name="test_structured_msg", schedulers={"default": mock_scheduler}
        )
        role = Role("ignored").runs("/bin/echo").on(self.test_container)
        app_handle = session.run(Application(app_id).of(role))
        status = none_throws(session.status(app_handle))
        self.assertEquals(resp.structured_error_msg, status.structured_error_msg)

    def test_wait_unknown_app(self, _) -> None:
        session = Runner(
            name=SESSION_NAME, schedulers={"default": self.scheduler}, wait_interval=1
        )
        self.assertIsNone(session.wait("default://test_session/unknown_app_id"))
        self.assertIsNone(session.wait("default://another_session/some_app"))

    def test_stop(self, _) -> None:
        session = Runner(
            name=SESSION_NAME, schedulers={"default": self.scheduler}, wait_interval=1
        )
        self.assertIsNone(session.stop("default://test_session/unknown_app_id"))

    def test_log_lines_unknown_app(self, _) -> None:
        session = Runner(
            name=SESSION_NAME, schedulers={"default": self.scheduler}, wait_interval=1
        )
        with self.assertRaises(UnknownAppException):
            session.log_lines("default://test_session/unknown", "trainer")

    def test_log_lines(self, _) -> None:
        app_id = "mock_app"

        scheduler_mock = MagicMock()
        scheduler_mock.describe.return_value = DescribeAppResponse(
            app_id, AppState.RUNNING
        )
        scheduler_mock.log_iter.return_value = iter(["hello", "world"])
        session = Runner(
            name=SESSION_NAME, schedulers={"default": scheduler_mock}, wait_interval=1
        )

        role_name = "trainer"
        replica_id = 2
        regex = "QPS.*"
        since = datetime.datetime.now()
        until = datetime.datetime.now()
        lines = list(
            session.log_lines(
                f"default://test_session/{app_id}",
                role_name,
                replica_id,
                regex,
                since,
                until,
            )
        )

        self.assertEqual(["hello", "world"], lines)
        scheduler_mock.log_iter.assert_called_once_with(
            app_id, role_name, replica_id, regex, since, until, False
        )

    def test_no_default_scheduler(self, _) -> None:
        with self.assertRaises(ValueError):
            Runner(name=SESSION_NAME, schedulers={"local": self.scheduler})

    @patch("json.dumps")
    def test_get_schedulers(self, json_dumps_mock: MagicMock, _) -> None:
        default_sched_mock = MagicMock()
        json_dumps_mock.return_value = "{}"
        local_sched_mock = MagicMock()
        schedulers = {"default": default_sched_mock, "local": local_sched_mock}
        session = Runner(name="test_session", schedulers=schedulers)

        role = Role(name="sleep").runs("sleep.sh", "60").on(self.test_container)
        app = Application("sleeper").of(role)
        cfg = RunConfig()
        session.run(app, scheduler="local", cfg=cfg)
        local_sched_mock.submit.called_once_with(app, cfg)
