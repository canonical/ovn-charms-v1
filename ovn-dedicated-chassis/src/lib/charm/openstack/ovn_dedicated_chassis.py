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

import charms_openstack.charm as charm

import charms.ovn_charm


charm.use_defaults('charm.default-select-release')


class OVNDedicatedChassisConfigurationAdapter(
        charms.ovn_charm.OVNConfigurationAdapter):
    """Provide a configuration adapter for OVN."""

    # The charm class initializer will look for these but they are not and will
    # not be in our config for the time being.
    enable_dpdk = False
    enable_sriov = False
    enable_hardware_offload = False


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
