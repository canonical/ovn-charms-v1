# Copyright 2019 Canonical Ltd
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

import os

import charmhelpers.core.hookenv as ch_hookenv
import charmhelpers.core.host as ch_host

import charms_openstack.charm as charm

import charms.ovn_charm


charm.use_defaults('charm.default-select-release')

FLOW_RESTORE_WAIT_SCRIPT_NAME = 'clear-ovn-flow-restore-wait'
FLOW_RESTORE_WAIT_SCRIPT = os.path.join(
    '/usr/local/sbin', FLOW_RESTORE_WAIT_SCRIPT_NAME)
OVN_CONTROLLER_DROPIN_DIR = '/etc/systemd/system/ovn-controller.service.d'
OVN_CONTROLLER_DROPIN = os.path.join(
    OVN_CONTROLLER_DROPIN_DIR, '50-charm-clear-flow-restore-wait.conf')
OVN_CONTROLLER_DROPIN_CONTENT = (
    '# Managed by the ovn-dedicated-chassis charm, do not edit.\n'
    '[Service]\n'
    'ExecStartPre=-{}\n'.format(FLOW_RESTORE_WAIT_SCRIPT))


class OVNDedicatedChassisConfigurationAdapter(
        charms.ovn_charm.OVNConfigurationAdapter):
    """Provide a configuration adapter for OVN."""

    # The charm class initializer will look for these but they are not and will
    # not be in our config for the time being.
    enable_dpdk = False
    enable_sriov = False


class OVNChassisCharm(charms.ovn_charm.DeferredEventMixin,
                      charms.ovn_charm.BaseOVNChassisCharm):
    # OpenvSwitch and OVN is distributed as part of the Ubuntu Cloud Archive
    # Pockets get their name from OpenStack releases
    #
    # This defines the earliest version this charm can support, actually
    # installed version is selected by configuration.
    source_config_key = 'source'
    release = 'ussuri'
    name = 'ovn-dedicated-chassis'
    configuration_class = OVNDedicatedChassisConfigurationAdapter

    # NOTE(fnordahl): Add this to ``layer-ovn``
    def install(self, check_deferred_events=True):
        self.configure_source()
        super().install(check_deferred_events=check_deferred_events)
        self.configure_flow_restore_wait_cleanup()

    def upgrade_charm(self):
        """Extend the default upgrade_charm method."""
        super().upgrade_charm()
        self.configure_flow_restore_wait_cleanup()

    def configure_flow_restore_wait_cleanup(self):
        """Make the chassis survive a reboot with flow-restore-wait set."""
        self.install_flow_restore_wait_cleanup()
        self.clear_flow_restore_wait()

    def install_flow_restore_wait_cleanup(self):
        """Clear OVN managed flow-restore-wait before ovn-controller starts.

        ovn-controller 24.03.8 deliberately leaves
        ``other_config:flow-restore-wait`` set on a chassis that is part of a
        HA chassis group, and only clears it after it has connected to the
        Southbound database.  A chassis that reaches the Southbound database
        over its own datapath can thus never clear the option, because
        ``ovs-vswitchd`` does not pass packets while the option is set.

        Clearing the option from a ``ExecStartPre`` of ``ovn-controller``
        breaks the deadlock without relying on anything that needs working
        connectivity, which is what makes this preferable to doing it from a
        charm hook.
        """
        with open(os.path.join(ch_hookenv.charm_dir(), 'files', 'scripts',
                               FLOW_RESTORE_WAIT_SCRIPT_NAME), 'r') as fin:
            ch_host.write_file(
                FLOW_RESTORE_WAIT_SCRIPT, fin.read(), perms=0o755)
        ch_host.mkdir(OVN_CONTROLLER_DROPIN_DIR, perms=0o755)
        ch_host.write_file(
            OVN_CONTROLLER_DROPIN, OVN_CONTROLLER_DROPIN_CONTENT,
            perms=0o644)
        self.run('systemctl', 'daemon-reload')

    def clear_flow_restore_wait(self):
        """Clear a stale OVN managed flow-restore-wait, if any.

        Recovers a unit that is already cut off, as the drop-in installed by
        ``install_flow_restore_wait_cleanup`` only takes effect the next time
        ovn-controller starts.
        """
        self.run(FLOW_RESTORE_WAIT_SCRIPT)
