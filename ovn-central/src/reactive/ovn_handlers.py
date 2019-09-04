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

import charms_openstack.bus
import charms_openstack.charm as charm


charms_openstack.bus.discover()

# Use the charms.openstack defaults for common states and hooks
charm.use_defaults(
    'charm.installed',
    'config.changed',
    'update-status',
    'upgrade-charm',
)


@reactive.when_not_all('config.default.ssl_ca',
                       'config.default.ssl_cert',
                       'config.default.ssl_key')
@reactive.when('config.rendered', 'config.changed')
def certificates_in_config_tls():
    # handle the legacy ssl_* configuration options
    with charm.provide_charm_instance() as ovn_charm:
        ovn_charm.configure_tls()
        ovn_charm.assess_status()


@reactive.when('charm.installed')
def render():
    with charm.provide_charm_instance() as ovn_charm:
        ovn_charm.render_with_interfaces([])
        if ovn_charm.enable_services():
            # belated enablement of default certificates handler due to the
            # ``ovsdb-server`` processes must have finished database
            # initialization and be running prior to configuring TLS
            charm.use_defaults('certificates.available')
            reactive.set_flag('config.rendered')
        ovn_charm.assess_status()
