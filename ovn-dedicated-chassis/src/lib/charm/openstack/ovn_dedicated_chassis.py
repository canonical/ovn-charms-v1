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

import charms_openstack.adapters
import charms_openstack.charm as charm

import charms.ovn_charm


charm.use_defaults('charm.default-select-release')


# NOTE(fnordahl): We should split the ``OVNConfigurationAdapter`` in
# ``layer-ovn`` into common and chassis specific parts so we can re-use the
# common parts here.
class OVNDedicatedChassisConfigurationAdapter(
        charms_openstack.adapters.ConfigurationAdapter):
    """Provide a configuration adapter for OVN."""

    # The charm class initializer will look for these but they are not and will
    # not be in our config for the time being.
    enable_dpdk = False
    enable_sriov = False
    enable_hardware_offload = False

    @property
    def ovn_key(self):
        return os.path.join(self.charm_instance.ovn_sysconfdir(), 'key_host')

    @property
    def ovn_cert(self):
        return os.path.join(self.charm_instance.ovn_sysconfdir(), 'cert_host')

    @property
    def ovn_ca_cert(self):
        return os.path.join(self.charm_instance.ovn_sysconfdir(),
                            '{}.crt'.format(self.charm_instance.name))

    @property
    def chassis_name(self):
        return self.charm_instance.get_ovs_hostname()


class TrainOVNChassisCharm(charms.ovn_charm.BaseTrainOVNChassisCharm):
    # OpenvSwitch and OVN is distributed as part of the Ubuntu Cloud Archive
    # Pockets get their name from OpenStack releases
    source_config_key = 'source'
    release = 'train'
    name = 'ovn-dedicated-chassis'
    configuration_class = OVNDedicatedChassisConfigurationAdapter

    # NOTE(fnordahl): Add this to ``layer-ovn``
    def install(self):
        self.configure_source()
        super().install()


class UssuriOVNChassisCharm(charms.ovn_charm.BaseUssuriOVNChassisCharm):
    # OpenvSwitch and OVN is distributed as part of the Ubuntu Cloud Archive
    # Pockets get their name from OpenStack releases
    source_config_key = 'source'
    release = 'ussuri'
    name = 'ovn-dedicated-chassis'
    configuration_class = OVNDedicatedChassisConfigurationAdapter

    # NOTE(fnordahl): Add this to ``layer-ovn``
    def install(self):
        self.configure_source()
        super().install()
