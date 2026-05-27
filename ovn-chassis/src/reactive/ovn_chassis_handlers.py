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
import charms.reactive as reactive
import charms_openstack.charm as charm

from . import ovn_chassis_charm_handlers


@reactive.when_not(ovn_chassis_charm_handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG)
def enable_ovn_chassis_handlers():
    reactive.set_flag(
        ovn_chassis_charm_handlers.OVN_CHASSIS_ENABLE_HANDLERS_FLAG)


@reactive.when_not('is-update-status-hook')
def configure_deferred_restarts():
    with charm.provide_charm_instance() as instance:
        instance.configure_deferred_restarts()


@reactive.when_none('charm.paused', 'is-update-status-hook')
@reactive.when('config.rendered')
@reactive.when_any('config.changed.nagios_context',
                   'config.changed.nagios_servicegroups',
                   'endpoint.nrpe-external-master.changed',
                   'nrpe-external-master.available')
def configure_nrpe():
    """Handle config-changed for NRPE options."""
    with charm.provide_charm_instance() as charm_instance:
        charm_instance.render_nrpe()
