# Copyright 2026 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest.mock as mock

import charms_openstack.test_utils as test_utils

import charm.openstack.ovn_dedicated_chassis as ovn_dedicated_chassis


class Helper(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        self.target = ovn_dedicated_chassis.OVNChassisCharm()
        self.target.options = mock.MagicMock()
        self.patch_object(self.target, 'run')


class TestInstallFlowRestoreWaitCleanup(Helper):

    def setUp(self):
        super().setUp()
        self.patch_object(ovn_dedicated_chassis, 'ch_host')
        self.patch_object(ovn_dedicated_chassis, 'ch_hookenv')
        self.ch_hookenv.charm_dir.return_value = '/var/lib/charm/unit'

    def test_installs_script_from_charm_directory(self):
        with mock.patch('builtins.open',
                        mock.mock_open(read_data='#!/bin/sh\n')) as mocked:
            self.target.install_flow_restore_wait_cleanup()
        mocked.assert_called_once_with(
            '/var/lib/charm/unit/files/scripts/clear-ovn-flow-restore-wait',
            'r')
        self.ch_host.write_file.assert_any_call(
            '/usr/local/sbin/clear-ovn-flow-restore-wait', '#!/bin/sh\n',
            perms=0o755)

    def test_installs_ovn_controller_dropin(self):
        with mock.patch('builtins.open', mock.mock_open(read_data='')):
            self.target.install_flow_restore_wait_cleanup()
        self.ch_host.mkdir.assert_called_once_with(
            '/etc/systemd/system/ovn-controller.service.d', perms=0o755)
        self.ch_host.write_file.assert_any_call(
            '/etc/systemd/system/ovn-controller.service.d/'
            '50-charm-clear-flow-restore-wait.conf',
            # The leading dash makes systemd start ovn-controller even if
            # the Open vSwitch database cannot be reached.
            '# Managed by the ovn-dedicated-chassis charm, do not edit.\n'
            '[Service]\n'
            'ExecStartPre=-/usr/local/sbin/clear-ovn-flow-restore-wait\n',
            perms=0o644)

    def test_reloads_systemd(self):
        # Without this the drop-in would only take effect after something
        # else happens to reload the systemd manager configuration.
        with mock.patch('builtins.open', mock.mock_open(read_data='')):
            self.target.install_flow_restore_wait_cleanup()
        self.run.assert_called_once_with('systemctl', 'daemon-reload')


class TestClearFlowRestoreWait(Helper):

    def test_runs_script(self):
        self.target.clear_flow_restore_wait()
        self.run.assert_called_once_with(
            '/usr/local/sbin/clear-ovn-flow-restore-wait')


class TestConfigureFlowRestoreWaitCleanup(Helper):

    def test_clears_after_installing_script(self):
        # The script has to be on disk before it can be run.
        calls = []
        self.patch_object(
            self.target, 'install_flow_restore_wait_cleanup',
            side_effect=lambda: calls.append('install'))
        self.patch_object(
            self.target, 'clear_flow_restore_wait',
            side_effect=lambda: calls.append('clear'))
        self.target.configure_flow_restore_wait_cleanup()
        self.assertEqual(['install', 'clear'], calls)


class TestInstall(Helper):

    def test_configures_cleanup_after_packages(self):
        # ``ovn-controller.service`` and ``ovs-vsctl`` are provided by the
        # packages installed by the base class.
        calls = []
        self.patch_object(self.target, 'configure_source')
        self.patch_object(
            self.target, 'configure_flow_restore_wait_cleanup',
            side_effect=lambda: calls.append('cleanup'))
        with mock.patch.object(
                ovn_dedicated_chassis.charms.ovn_charm.DeferredEventMixin,
                'install',
                side_effect=lambda **kwargs: calls.append('super')):
            self.target.install()
        self.assertEqual(['super', 'cleanup'], calls)


class TestUpgradeCharm(Helper):

    def test_configures_cleanup(self):
        # Picks up the fix on units deployed before it was available.
        self.patch_object(self.target, 'configure_flow_restore_wait_cleanup')
        with mock.patch.object(
                ovn_dedicated_chassis.charms.ovn_charm.BaseOVNChassisCharm,
                'upgrade_charm'):
            self.target.upgrade_charm()
        self.configure_flow_restore_wait_cleanup.assert_called_once_with()
